"""Command line of the review checks, run as python -m peercheck.reviews or through peercheck --reviews.

The review checks load PyTorch and the detector models, therefore they run in their own process. CoCoDet and
EditLens label each review, and the report gives the result of each detector on its own. A CoCoDet label AI marks
the review for a closer look. An EditLens label is a second opinion beside it and marks no review. The canary,
near-duplicate, and citation checks need no model.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from dataclasses import replace
from pathlib import Path

from peercheck import canary, inputs, report, tools
from peercheck import profile as profiles
from peercheck.findings import Finding, Severity, needs_review
from peercheck.models import Review
from peercheck.reviews import citations, cocodet, duplicates, editlens

DETECTORS = ("cocodet", "editlens")
CHECKS = ("duplicates", "citations")
CAUTION = ("CoCoDet and EditLens give leads, not verdicts. The CoCoDet model card states that it \"should not be "
           "used as the sole arbiter of academic misconduct\". The Open Pangram release states that EditLens "
           "\"should NOT be used to enforce any sort of AI usage policy in an educational or professional setting\".")
CANARY_STATES = (("canary.hit", "hit"), ("canary.untested", "untested"), ("canary.no-key", "no key"))
# The page of the reviews keeps the labels and scores of the detectors; their details stay in the workbook.
DETAIL_COLUMNS = ("CoCoDet Detail", "Content Sources", "Style Sources", "CoCoDet Notes", "EditLens Notes")


def main(argv: list[str] | None = None) -> int:
    """Run the review checks."""
    args = parser().parse_args(argv)
    try:
        return run(args)
    except (inputs.InputError, profiles.ProfileError, tools.ToolError, cocodet.ModelError, editlens.ModelError,
            OSError, ValueError) as exc:
        print(f"peercheck: {exc}", file=sys.stderr)
        return 2


def parser() -> argparse.ArgumentParser:
    """Build the parser of the review command line."""
    top = argparse.ArgumentParser(prog="peercheck --reviews",
                                  description="Check the reviews of a folder or a file.")
    top.add_argument("folder", help="folder or file of the reviews")
    top.add_argument("--template", help="the template of the venue, with the settings of the review checks")
    top.add_argument("--canaries", type=Path, help="key file of peercheck --canary, to find reviews that contain the "
                                                   "citation hidden in their paper")
    top.add_argument("--dblp-index", type=Path, help="dblp index saved by peercheck --conflicts, to match "
                                                     "requested citations against works of the reviewers")
    top.add_argument("--out", type=Path, default=Path("reviews.xlsx"), help="Excel report, with the HTML page for the browser beside it (default reviews.xlsx)")
    top.add_argument("--json", type=Path, help="also write the results as JSON")
    return top


def run(args: argparse.Namespace) -> int:
    """Check every review of a folder and write the report."""
    venue = profiles.load(args.template or profiles.DEFAULT)
    detectors, skipped = _detectors(venue)
    checks = tuple(name for name in CHECKS if _runs(venue, name))
    off = [name for name in (*DETECTORS, *CHECKS) if not _runs(venue, name)]
    if args.canaries and not _runs(venue, "canary"):
        off.append("canary")
    if off:
        print(f"The template turns off {', '.join(off)}.", file=sys.stderr)
    key = canary.read_key(args.canaries) if args.canaries and _runs(venue, "canary") else None
    reviews, found = _unique_ids(inputs.read_reviews(Path(args.folder)))
    rows = {r.review_id: _row(r) for r in reviews}
    texts = [r.author_text for r in reviews]
    labels = cocodet.Detector().label(texts) if "cocodet" in detectors else None
    lenses = editlens.Detector().label(texts) if "editlens" in detectors else None
    for index, review in enumerate(reviews):
        verdict = labels[index] if labels else None
        lens = lenses[index] if lenses else None
        rows[review.review_id].update(_detector_columns(verdict, lens))
        found[review.review_id].extend(_detector_findings(verdict, lens))
    canaries = [("Canaries", str(args.canaries) if key is not None else "none")]
    if key is not None:
        for review_id, items in canary.check_reviews(reviews, key, _options(venue, "canary")).items():
            found[review_id].extend(items)
            rows[review_id]["Canary"] = _canary_state(items)
        canaries.append(("Reviewed papers in the canary key", _key_coverage(reviews, key)))
    pages = {"pages": venue.format.main_pages} if venue else {}
    options = {"duplicates": _options(venue, "duplicates"),
               "citations": {**pages, **_options(venue, "citations"),
                             **_panel_options(args)}}
    for name, module in (("duplicates", duplicates), ("citations", citations)):
        if name in checks:
            for review_id, items in module.check_reviews(reviews, options[name]).items():
                found[review_id].extend(items)
    for review in reviews:
        rows[review.review_id]["Needs Review"] = "yes" if needs_review(found[review.review_id]) else "no"
        rows[review.review_id]["Findings"] = "\n".join(
            f.as_text() for f in found[review.review_id] if f.severity is not Severity.INFO)
    report.write_sheets(args.out, {"Reviews": list(rows.values())},
                        [(rid, f) for rid, items in found.items() for f in items],
                        [("Detectors", ", ".join(detectors) or "none"), *[("Skipped", note) for note in skipped],
                         ("Checks", ", ".join(checks) or "none"),
                         *canaries, ("Caution", CAUTION)])
    if args.json:
        report.write_json(args.json, {"reviews": list(rows.values()), "findings": found})
    page = args.out.with_suffix(".html")
    report.write_rows_html(page, "PeerCheck, Reviews", list(rows.values()), found, "Review ID", DETAIL_COLUMNS, skipped)
    flagged = sum(1 for items in found.values() if needs_review(items))
    print(f"{len(reviews)} reviews checked, {flagged} need review. Report: {page} and {args.out}")
    return 0


def _unique_ids(reviews: list[Review]) -> tuple[list[Review], dict[str, list[Finding]]]:
    """Number each repeat of a review ID from #2; return the reviews and a note on each review that shares an ID."""
    counts = Counter(review.review_id for review in reviews)
    notes = {review_id: f"{count} reviews share the ID {review_id}; the report numbers the repeats from #2"
             for review_id, count in counts.items() if count > 1}
    for note in notes.values():
        print(f"peercheck: {note}", file=sys.stderr)
    taken = set(counts)
    numbers: Counter[str] = Counter()
    unique: list[Review] = []
    found: dict[str, list[Finding]] = {}
    for review in reviews:
        original = review_id = review.review_id
        numbers[original] += 1
        if numbers[original] > 1:
            while f"{original}#{numbers[original]}" in taken:
                numbers[original] += 1
            review_id = f"{original}#{numbers[original]}"
            taken.add(review_id)
        unique.append(replace(review, review_id=review_id))
        found[review_id] = [Finding("input.repeated-id", Severity.INFO, notes[original])] if original in notes else []
    return unique, found


def _key_coverage(reviews: list[Review], key: dict[int, str]) -> str:
    papers = {review.paper_id for review in reviews if review.paper_id is not None}
    covered = papers & set(key)
    if not covered:
        print("peercheck: the canary key holds none of the reviewed papers; check that the key belongs to "
              "these reviews", file=sys.stderr)
    return f"{len(covered)} of {len(papers)}"


def _panel_options(args: argparse.Namespace) -> dict[str, object]:
    return {"dblp_index": args.dblp_index} if args.dblp_index else {}


def _detectors(venue) -> tuple[tuple[str, ...], list[str]]:
    """Return the detectors whose keys stand in the template and a note when no Hugging Face token is set."""
    detectors = tuple(name for name in DETECTORS if _runs(venue, name))
    if "editlens" in detectors and not editlens.has_token():
        note = "EditLens skipped, since no Hugging Face token is set. The README describes EditLens access."
        print(note, file=sys.stderr)
        return tuple(name for name in detectors if name != "editlens"), [note]
    return detectors, []


def _row(review: Review) -> dict[str, object]:
    scores = review.scores
    return {"Source File": review.source, "Submission": review.paper_id, "Review ID": review.review_id,
            "Title": review.title,
            # Review forms name the two common scores differently.
            "Overall Evaluation": scores.get("Overall evaluation") or scores.get("Overall merit"),
            "Reviewer's Confidence": scores.get("Reviewer's confidence") or scores.get("Reviewer expertise"),
            "Words for Authors": editlens.count_words(review.author_text)}


def _detector_columns(verdict, lens) -> dict[str, object]:
    columns: dict[str, object] = {}
    if verdict is not None:
        columns.update({"CoCoDet Verdict": verdict.label.upper(), "CoCoDet Detail": verdict.fine_name,
                        "CoCoDet P(AI)": verdict.probabilities.get("ai"),
                        "Content Sources": ", ".join(verdict.content_sources),
                        "Style Sources": ", ".join(verdict.style_sources), "CoCoDet Notes": "; ".join(verdict.notes)})
    if lens is not None:
        columns.update({"EditLens Label": lens.label.upper(), "EditLens Score": lens.score,
                        "EditLens Notes": "; ".join(lens.notes)})
    return columns


# The words of each EditLens label other than Human in a finding.
EDITLENS_LABELS = {"ai": "AI-generated", "ai-edited": "AI-edited"}


def _detector_findings(verdict, lens) -> list[Finding]:
    """Report the result of each detector on its own: a CoCoDet label AI marks the review for a closer look, and an
    EditLens label other than Human becomes a note beside it."""
    found = []
    if verdict is not None and verdict.label == "ai":
        found.append(Finding("cocodet.ai", Severity.WARNING, "CoCoDet labels the review as AI-generated",
                             evidence=f"CoCoDet P(AI) {verdict.probabilities.get('ai')}"))
    # EditLens labels most reviews that AI polished as AI-edited, therefore its label marks no review.
    if lens is not None and lens.label in EDITLENS_LABELS:
        found.append(Finding(f"editlens.{lens.label}", Severity.INFO,
                             f"EditLens labels the review as {EDITLENS_LABELS[lens.label]}",
                             evidence=f"EditLens score {lens.score:.4f}"))
    return found


def _canary_state(items: list[Finding]) -> str:
    codes = {f.check for f in items}
    return next((state for code, state in CANARY_STATES if code in codes), "no")


def _options(venue, check: str) -> dict:
    return venue.options(check) if venue else {}


def _runs(venue, check: str) -> bool:
    return venue.runs(check) if venue else True

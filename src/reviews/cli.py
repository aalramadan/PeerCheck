"""Command line of the review checks, run as python -m peercheck.reviews or through peercheck reviews.

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

from peercheck import canary, conflicts, inputs, report, tools
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
    """Run the review checks or download their models."""
    args = parser().parse_args(argv)
    try:
        if args.folder == "setup":
            return setup(args.extra[0] if args.extra else "cocodet", args.device)
        return run(args)
    except (inputs.InputError, profiles.ProfileError, tools.ToolError, cocodet.ModelError, editlens.ModelError,
            OSError, ValueError) as exc:
        print(f"peercheck reviews: {exc}", file=sys.stderr)
        return 2


def parser() -> argparse.ArgumentParser:
    """Build the parser of the review command line."""
    top = argparse.ArgumentParser(prog="peercheck reviews",
                                  description="Check reviews exported from EasyChair (XML) or HotCRP (CSV).")
    top.add_argument("folder", help="folder or file of review exports, or setup to download the models")
    top.add_argument("extra", nargs="*", help="after setup: cocodet or editlens")
    top.add_argument("--profile", default="icse-2027", help="venue profile key or YAML file")
    top.add_argument("--detectors", default="cocodet,editlens", help="comma-separated subset of cocodet,editlens")
    top.add_argument("--checks", default="duplicates,citations", help="comma-separated subset of duplicates,citations")
    top.add_argument("--canaries", type=Path, help="key file of peercheck canary, to find reviews that contain the "
                                                   "citation hidden in their paper")
    top.add_argument("--device", choices=("cpu", "cuda"), help="cpu or cuda (default: cuda when available)")
    top.add_argument("--dblp-index", type=Path, help="dblp index saved by peercheck conflicts, to match "
                                                     "requested citations against works of the reviewers")
    top.add_argument("--reviewer-csv", type=Path, help="EasyChair reviewer.csv, with --assignment-csv")
    top.add_argument("--assignment-csv", type=Path, help="EasyChair assignment.csv: who reviews which paper")
    top.add_argument("--out", type=Path, default=Path("reviews.xlsx"), help="Excel report (default reviews.xlsx)")
    top.add_argument("--json", type=Path, help="also write the results as JSON")
    top.add_argument("--html", type=Path, help="also write an HTML page for viewing in a browser")
    return top


def setup(what: str, device: str | None) -> int:
    """Download the models of one detector into the cache."""
    if what == "cocodet":
        cocodet.Detector(device="cpu")
    elif what == "editlens":
        editlens.Detector(device="cpu")
    else:
        raise ValueError(f"unknown model {what!r}; choose cocodet or editlens")
    print(f"{what} is ready in the Hugging Face cache")
    return 0


def run(args: argparse.Namespace) -> int:
    """Check every review of a folder and write the report."""
    venue = profiles.load(args.profile)
    detectors = _choose(args.detectors, DETECTORS, "detectors")
    checks = _choose(args.checks, CHECKS, "checks")
    key = canary.read_key(args.canaries) if args.canaries else None
    reviews, found = _unique_ids(inputs.read_reviews(Path(args.folder)))
    rows = {r.review_id: _row(r) for r in reviews}
    texts = [r.author_text for r in reviews]
    labels = cocodet.Detector(args.device).label(texts) if "cocodet" in detectors else None
    lenses = editlens.Detector(args.device).label(texts) if "editlens" in detectors else None
    for index, review in enumerate(reviews):
        verdict = labels[index] if labels else None
        lens = lenses[index] if lenses else None
        rows[review.review_id].update(_detector_columns(verdict, lens))
        found[review.review_id].extend(_detector_findings(verdict, lens))
    canaries = [("Canaries", str(args.canaries) if args.canaries else "none")]
    if key is not None:
        for review_id, items in canary.check_reviews(reviews, key, venue.options("canary")).items():
            found[review_id].extend(items)
            rows[review_id]["Canary"] = _canary_state(items)
        canaries.append(("Reviewed papers in the canary key", _key_coverage(reviews, key)))
    options = {"duplicates": venue.options("duplicates"),
               "citations": {"pages": venue.format.main_pages, **venue.options("citations"),
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
                        [("Detectors", ", ".join(detectors) or "none"), ("Checks", ", ".join(checks) or "none"),
                         *canaries, ("Caution", CAUTION)])
    if args.json:
        report.write_json(args.json, {"reviews": list(rows.values()), "findings": found})
    if args.html:
        report.write_rows_html(args.html, "PeerCheck, Reviews", list(rows.values()), found, "Review ID", DETAIL_COLUMNS)
    flagged = sum(1 for items in found.values() if needs_review(items))
    print(f"{len(reviews)} reviews checked, {flagged} need review. Report: {args.out}")
    return 0


def _unique_ids(reviews: list[Review]) -> tuple[list[Review], dict[str, list[Finding]]]:
    """Number each repeat of a review ID from #2; return the reviews and a note on each review that shares an ID."""
    counts = Counter(review.review_id for review in reviews)
    notes = {review_id: f"{count} reviews share the ID {review_id}; the report numbers the repeats from #2"
             for review_id, count in counts.items() if count > 1}
    for note in notes.values():
        print(f"peercheck reviews: {note}", file=sys.stderr)
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
        print("peercheck reviews: the canary key holds none of the reviewed papers; check that the key belongs to "
              "these reviews", file=sys.stderr)
    return f"{len(covered)} of {len(papers)}"


def _panel_options(args: argparse.Namespace) -> dict[str, object]:
    options: dict[str, object] = {}
    if args.dblp_index:
        options["dblp_index"] = args.dblp_index
    if args.assignment_csv:
        if not args.reviewer_csv:
            raise inputs.InputError("--assignment-csv needs --reviewer-csv for the member IDs")
        options["assignments"] = conflicts.read_pairs(args.assignment_csv, conflicts.read_members(args.reviewer_csv))
    return options


def _choose(text: str, allowed: tuple[str, ...], what: str) -> tuple[str, ...]:
    names = tuple(name.strip() for name in text.split(",") if name.strip())
    unknown = sorted(set(names) - set(allowed))
    if unknown:
        raise ValueError(f"unknown {what} {', '.join(unknown)}; choose from {', '.join(allowed)}")
    return names


def _row(review: Review) -> dict[str, object]:
    scores = review.scores
    return {"Source File": review.source, "Submission": review.paper_id, "Review ID": review.review_id,
            "Title": review.title,
            # EasyChair and HotCRP name the two common scores differently.
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

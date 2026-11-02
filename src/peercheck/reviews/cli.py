"""Command line of the review checks, run as python -m peercheck.reviews or through peercheck reviews.

The review checks load PyTorch and the detector models, therefore they run in their own process. CoCoDet
labels each review, Binoculars gives a second opinion, and a review counts as flagged only when the two
detectors agree, as ICLR 2026 forwarded only reviews that two detectors flagged. The near-duplicate and
citation checks need no model.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from peercheck import conflicts, inputs, report, tools
from peercheck import profile as profiles
from peercheck.findings import Finding, Severity, needs_review
from peercheck.models import Review
from peercheck.reviews import binoculars, citations, cocodet, duplicates

DETECTORS = ("cocodet", "binoculars")
CHECKS = ("duplicates", "citations")
CAUTION = ("CoCoDet and Binoculars give leads, not verdicts. The CoCoDet model card states that it "
           "\"should not be used as the sole arbiter of academic misconduct\".")


def main(argv: list[str] | None = None) -> int:
    """Run the review checks or download their models."""
    args = parser().parse_args(argv)
    try:
        if args.folder == "setup":
            return setup(args.extra[0] if args.extra else "cocodet", args.device)
        return run(args)
    except (inputs.InputError, profiles.ProfileError, tools.ToolError, cocodet.ModelError, OSError,
            ValueError) as exc:
        print(f"peercheck reviews: {exc}", file=sys.stderr)
        return 2


def parser() -> argparse.ArgumentParser:
    """Build the parser of the review command line."""
    top = argparse.ArgumentParser(prog="peercheck reviews", description="Check EasyChair review XML files.")
    top.add_argument("folder", help="folder with review XML files, or setup to download the models")
    top.add_argument("extra", nargs="*", help="after setup: cocodet or binoculars")
    top.add_argument("--profile", default="icsme-2026", help="venue profile key or YAML file")
    top.add_argument("--detectors", default="cocodet,binoculars", help="comma-separated subset of cocodet,binoculars")
    top.add_argument("--checks", default="duplicates,citations", help="comma-separated subset of duplicates,citations")
    top.add_argument("--device", default=None, help="cpu or cuda (default: cuda when available)")
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
    elif what == "binoculars":
        binoculars.install()
    else:
        raise ValueError(f"unknown model {what!r}; choose cocodet or binoculars")
    print(f"{what} is ready in the Hugging Face cache")
    return 0


def run(args: argparse.Namespace) -> int:
    """Check every review of a folder and write the report."""
    venue = profiles.load(args.profile)
    detectors = _choose(args.detectors, DETECTORS, "detectors")
    checks = _choose(args.checks, CHECKS, "checks")
    reviews = inputs.read_reviews(Path(args.folder))
    rows = {r.review_id: _row(r) for r in reviews}
    found: dict[str, list[Finding]] = {r.review_id: [] for r in reviews}
    texts = [r.author_text for r in reviews]
    labels = cocodet.Detector(args.device).label(texts) if "cocodet" in detectors else None
    second_options = venue.options("binoculars") | ({"device": args.device} if args.device else {})
    scores = binoculars.score(texts, second_options) if "binoculars" in detectors else None
    for index, review in enumerate(reviews):
        verdict = labels[index] if labels else None
        second = scores[index] if scores else None
        rows[review.review_id].update(_detector_columns(verdict, second))
        found[review.review_id].extend(_detector_findings(verdict, second, scores is not None))
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
                         ("Caution", CAUTION)])
    if args.json:
        report.write_json(args.json, {"reviews": list(rows.values()), "findings": found})
    if args.html:
        report.write_rows_html(args.html, "PeerCheck, reviews", list(rows.values()), found, "Review ID")
    flagged = sum(1 for items in found.values() if needs_review(items))
    print(f"{len(reviews)} reviews checked, {flagged} need review. Report: {args.out}")
    return 0


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
            "Title": review.title, "Overall Evaluation": scores.get("Overall evaluation"),
            "Reviewer's Confidence": scores.get("Reviewer's confidence"),
            "Words for Authors": len(review.author_text.split())}


def _detector_columns(verdict, second) -> dict[str, object]:
    columns: dict[str, object] = {}
    if verdict is not None:
        columns.update({"CoCoDet Verdict": verdict.label.upper(), "CoCoDet Detail": verdict.fine_name,
                        "CoCoDet P(AI)": verdict.probabilities.get("ai"),
                        "Content Sources": ", ".join(verdict.content_sources),
                        "Style Sources": ", ".join(verdict.style_sources), "CoCoDet Notes": "; ".join(verdict.notes)})
    if second is not None:
        columns.update({"Binoculars Score": None if second.score is None else round(second.score, 4),
                        "Binoculars Threshold": round(second.threshold, 4),
                        "Binoculars Machine": "yes" if second.machine else "no"})
    return columns


def _detector_findings(verdict, second, two_detectors: bool) -> list[Finding]:
    if verdict is None or verdict.label != "ai":
        return []
    if not two_detectors:
        return [Finding("detectors.cocodet-ai", Severity.INFO, "CoCoDet labels the content as AI; no second detector ran")]
    if second is not None and second.machine:
        return [Finding("detectors.agree-ai", Severity.WARNING,
                        "CoCoDet and Binoculars agree that the review reads as machine-written",
                        evidence=f"P(AI) {verdict.probabilities.get('ai')}, Binoculars score {second.score:.4f} "
                                 f"below threshold {second.threshold:.4f}")]
    return [Finding("detectors.cocodet-ai", Severity.INFO, "CoCoDet labels the content as AI; Binoculars does not")]

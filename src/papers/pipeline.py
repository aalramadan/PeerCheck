"""Runs the paper checks over a folder of submission PDFs and collects one result per paper."""

from __future__ import annotations

import concurrent.futures
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from peercheck import inputs
from peercheck.findings import Finding, Severity, count
from peercheck.models import Paper
from peercheck.papers import (
    accessibility,
    active_content,
    density,
    embedded_identity,
    fonts,
    hidden_text,
    images,
    layout,
    line_numbers,
    margins,
    pdf_integrity,
    references,
    sigsoft,
    title_match,
    unreadable_text,
    unresolved_references,
)
from peercheck.papers.paper_processes import Failed, PaperProcesses, processors
from peercheck.profile import Profile

PAPER_CHECKS = ("layout", "sigsoft", "hidden-text", "references")
# The template key of each check. A check runs only while its key stands in the template.
PROFILE_KEYS = {"layout": "layout", "sigsoft": "sigsoft", "hidden-text": "hidden_text", "references": "references"}
SINGLE_CHECKS = {"hidden-text": hidden_text.check}
# Checks of PeerCheck that run with a check of an external tool and share its switch, under their own code prefix.
COMPANION_CHECKS = {
    "layout": (("pdf", pdf_integrity.check), ("fonts", fonts.check), ("margins", margins.check),
               ("unresolved", unresolved_references.check), ("text", unreadable_text.check),
               ("accessibility", accessibility.check), ("title", title_match.check),
               ("line-numbers", line_numbers.check), ("images", images.check)),
    "sigsoft": (("identity", embedded_identity.check),),
    "hidden-text": (("active-content", active_content.check),),
}
# A PDF that cannot open makes every other check fail, and these failures repeat the cause.
UNOPENED = {"pdf.password", "pdf.unreadable"}
# Papers that the checks read at the same time, each in a process of its own.
WORKERS = min(8, processors())
# Seconds that the checks of one paper get before their process ends, since a damaged PDF may never return.
PAPER_SECONDS = 900


@dataclass
class PaperResult:
    """The layout and the findings of one paper."""

    paper: Paper
    layout: layout.Layout | None = None
    findings: list[Finding] = field(default_factory=list)


@dataclass
class PapersRun:
    """The results of all papers of a folder, with the files that matched no paper and the papers with no file."""

    results: list[PaperResult]
    titles: dict[int, str]
    numbered: dict[int, str]
    duplicates: list[str]
    checks: tuple[str, ...]
    missing_pdfs: list[int] = field(default_factory=list)


def selected_checks(requested: list[str] | None, profile: Profile) -> tuple[str, ...]:
    """Return the checks to run: the requested ones, or every check whose key stands in the template."""
    names = requested or list(PAPER_CHECKS)
    unknown = sorted(set(names) - set(PAPER_CHECKS))
    if unknown:
        raise ValueError(f"unknown checks {', '.join(unknown)}; choose from {', '.join(PAPER_CHECKS)}")
    if requested:
        return tuple(names)
    return tuple(name for name in names if profile.runs(PROFILE_KEYS[name]))


def run_papers(pdf_folder: Path, profile: Profile, submissions: Path | None = None, authors: Path | None = None,
               checks: list[str] | None = None, workdir: Path | None = None) -> PapersRun:
    """Run the selected checks on every PDF of a folder and return the results."""
    found = inputs.find_pdfs(pdf_folder, profile)
    titles = inputs.read_submissions(submissions, profile) if submissions else {}
    people = inputs.read_people(authors, with_paper=True) if authors else {}
    papers = [Paper(paper_id, path, titles.get(paper_id, ""), tuple(people.get(paper_id, ())))
              for paper_id, path in sorted(found.papers.items())]
    names = selected_checks(checks, profile)
    with tempfile.TemporaryDirectory(prefix="peercheck-") as scratch, _pool(len(papers)) as pool:
        folder = workdir or Path(scratch)
        results = {paper.paper_id: PaperResult(paper) for paper in papers}
        if submissions:
            for paper_id in set(results) - set(titles):
                results[paper_id].findings.append(
                    Finding("input.not-in-sheet", Severity.WARNING, "PDF has no row in the submissions file"))
        for paper_id in found.numbered:
            results[paper_id].findings.append(Finding(
                "input.numbered", Severity.INFO, "the file name holds no paper number; PeerCheck numbered the PDF"))
        for name in found.duplicates:
            repeated = profile.paper_id(name)
            if repeated in results:
                results[repeated].findings.append(Finding(
                    "input.repeated-pdf", Severity.WARNING, "another PDF has this paper number and was not checked"))
        # The pool checks each paper while this process runs the checks that take all papers in one run.
        jobs = [pool.submit(_paper_checks, paper, profile, names, folder) for paper in papers]
        if "sigsoft" in names:
            for paper_id, found_issues in sigsoft.check_batch(papers, profile, folder).items():
                results[paper_id].findings.extend(found_issues)
        looked_up = _references(papers, profile, folder) if "references" in names else {}
        for number, (paper, job) in enumerate(zip(papers, jobs), start=1):
            result = results[paper.paper_id]
            result.layout, format_findings, findings = _outcome(job)
            result.findings = _without_repeats(
                format_findings + result.findings + findings + looked_up.get(paper.paper_id, []))
            _progress(number, len(papers), paper, result.findings)
        if "layout" in names:
            for paper_id, found_issues in _density(results, profile).items():
                results[paper_id].findings.extend(found_issues)
    return PapersRun(list(results.values()), titles, found.numbered, found.duplicates, names,
                     sorted(set(titles) - set(found.papers)))


class _SameProcess(concurrent.futures.Executor):
    """Runs each job in this process as soon as it comes in."""

    def submit(self, fn, /, *args, **kwargs):
        future: concurrent.futures.Future = concurrent.futures.Future()
        future.set_result(fn(*args, **kwargs))
        return future


def _pool(papers: int) -> concurrent.futures.Executor:
    """Return processes for the checks of several papers, or this process for a single paper."""
    workers = min(WORKERS, papers)
    return PaperProcesses(workers, PAPER_SECONDS) if workers > 1 else _SameProcess()


def _paper_checks(paper: Paper, profile: Profile, names: tuple[str, ...],
                  folder: Path) -> tuple[layout.Layout | None, list[Finding], list[Finding]]:
    """Run the checks that look at one paper alone and return its layout, the findings of the format check, and the
    findings of the other checks."""
    try:
        inspected = layout.inspect(paper, profile) if "layout" in names else layout.LayoutResult(None, [])
    except Exception as exc:  # noqa: BLE001
        failure = Finding("layout.error", Severity.WARNING, f"{type(exc).__name__}: {exc}")
        inspected = layout.LayoutResult(None, [failure])
    findings = []
    for name in names:
        for prefix, companion in COMPANION_CHECKS.get(name, ()):
            findings.extend(_guarded(prefix, companion, paper, profile, folder))
        if name in SINGLE_CHECKS:
            findings.extend(_guarded(name, SINGLE_CHECKS[name], paper, profile, folder))
    return inspected.layout, inspected.findings, findings


def _outcome(job: concurrent.futures.Future) -> tuple[layout.Layout | None, list[Finding], list[Finding]]:
    """Return the outcome of the checks of one paper. A paper whose checks end their process or run out of time, as
    on a damaged PDF, goes without them."""
    try:
        return job.result()
    except Failed as failure:
        return None, [Finding("pdf.error", Severity.WARNING, str(failure))], []


def _references(papers: list[Paper], profile: Profile, folder: Path) -> dict[int, list[Finding]]:
    # A failure inside the reference check must never stop the batch.
    print(f"Looking up the references of {len(papers)} papers.", file=sys.stderr)
    try:
        return references.check_batch(papers, profile, folder)
    except Exception as exc:  # noqa: BLE001
        return {paper.paper_id: [Finding("references.error", Severity.WARNING, f"{type(exc).__name__}: {exc}")]
                for paper in papers}


def _without_repeats(findings: list[Finding]) -> list[Finding]:
    """Drop the failures that a PDF which cannot open causes, a second note of a repair, and a second note of a
    script."""
    codes = {f.check for f in findings}
    unopened = codes & UNOPENED
    return [f for f in findings
            if not (unopened and f.check.endswith(".error"))
            and not (f.check == "hidden-text.damaged-pdf" and "pdf.damaged" in codes)
            and not (f.check == "hidden-text.javascript" and "active-content.javascript" in codes)]


def _density(results: dict[int, PaperResult], profile: Profile) -> dict[int, list[Finding]]:
    # The density check compares each paper with the whole batch, therefore it runs once every paper is measured.
    measures = {}
    for paper_id, result in results.items():
        try:
            measures[paper_id] = density.measure(result.paper, result.layout)
        except Exception:  # noqa: BLE001
            measures[paper_id] = None
    try:
        return density.check_batch(measures, profile)
    except Exception as exc:  # noqa: BLE001
        return {paper_id: [Finding("density.error", Severity.WARNING, f"{type(exc).__name__}: {exc}")]
                for paper_id in results}


def _guarded(name: str, check, paper: Paper, profile: Profile, workdir: Path) -> list[Finding]:
    # A failure inside one check of one paper must never stop the batch.
    try:
        return check(paper, profile, workdir)
    except Exception as exc:  # noqa: BLE001
        return [Finding(f"{name}.error", Severity.WARNING, f"{type(exc).__name__}: {exc}")]


def _progress(number: int, total: int, paper: Paper, findings: list[Finding]) -> None:
    errors, warnings = count(findings, Severity.ERROR), count(findings, Severity.WARNING)
    print(f"[{number}/{total}] paper {paper.paper_id}: {errors} error(s), {warnings} warning(s)", file=sys.stderr)

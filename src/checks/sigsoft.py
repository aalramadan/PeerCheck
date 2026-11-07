"""Anonymity and template check with the SIGSOFT submission checker, revised for PeerCheck.

The SIGSOFT submission checker was built for ICSE 2021 and reads each PDF with PDFBox. The revised jar
in external/submission-checker scans every page, the metadata, and the links of a PDF for the authors of the
paper, author emails, links that point to a person, acknowledgments, and self-citations, and prints one
JSON object per PDF. Options come from the profile: style, page limits, and file pattern from the format
rules, and allowed_hosts and flag_acknowledgments under checks.anonymity.
"""

from __future__ import annotations

import csv
import json
import re
import subprocess
from pathlib import Path

from peercheck import tools
from peercheck.findings import Finding, Severity
from peercheck.models import Paper
from peercheck.profile import Profile

SECONDS_PER_PAPER = 60
# The exit status of the checker when it rejects its arguments, such as a file it cannot find.
USAGE_ERROR = 2
JAVA_EXCEPTION = re.compile(r'Exception in thread "[^"]*" ([\w.$]+)')
SEVERITY = {
    "wrong-template": Severity.ERROR,
    "author-revealing-email": Severity.ERROR,
    "possibly-identity-revealing-data": Severity.ERROR,
    # Citing one's own work in the third person is allowed under double-anonymous review.
    "identity-data-in-references": Severity.INFO,
    "possibly-author-revealing-meta-data": Severity.WARNING,
    "previous-work-mentioned": Severity.WARNING,
    "identity-link": Severity.WARNING,
    "acknowledgments-present": Severity.WARNING,
    # The layout check owns the page limits; the SIGSOFT counts serve as a second opinion.
    "oversize": Severity.WARNING,
    "reference-page-after-limit": Severity.WARNING,
    "non-references-after-limit": Severity.WARNING,
    "paper-very-short": Severity.INFO,
}
MESSAGES = {
    "wrong-template": "not the expected template",
    "author-revealing-email": "author email",
    "possibly-identity-revealing-data": "author name, email, or affiliation of this paper",
    "identity-data-in-references": "the reference list cites a work by an author of this paper",
    "possibly-author-revealing-meta-data": "PDF metadata may name an author",
    "previous-work-mentioned": "self-citation in the first person",
    "identity-link": "link that may identify the authors",
    "acknowledgments-present": "acknowledgments section",
    "oversize": "more pages than main text plus references allow",
    "reference-page-after-limit": "references start after the page limit",
    "non-references-after-limit": "text other than references after the page limit",
    "paper-very-short": "very short paper",
}


def check_batch(papers: list[Paper], profile: Profile, workdir: Path) -> dict[int, list[Finding]]:
    """Run the checker once over all papers and return the findings of each paper.

    A PDF that stops the checker, such as one that exhausts its memory, leaves the papers after it without a record.
    Each paper without a record then runs again alone, with a time limit of its own.
    """
    if not papers:
        return {}
    command = _command(papers, profile, workdir)
    try:
        results, missing = _check(command, papers, SECONDS_PER_PAPER * len(papers))
        if len(papers) > 1:
            for paper in missing:
                alone, _ = _check(command, [paper], SECONDS_PER_PAPER)
                results.update(alone)
    except OSError as exc:
        reason = exc.strerror or type(exc).__name__
        return {paper.paper_id: [_error(f"the SIGSOFT checker did not start ({reason})")] for paper in papers}
    return results


def check(paper: Paper, profile: Profile, workdir: Path) -> list[Finding]:
    """Return the findings of the checker for one paper."""
    return check_batch([paper], profile, workdir)[paper.paper_id]


def findings(record: dict) -> list[Finding]:
    """Turn one JSON record of the checker into findings, keeping the issues of a PDF that opened."""
    found = []
    if record.get("error"):
        error = str(record["error"])
        file = str(record.get("file") or "")
        # The report leaves out file names, and the checker names the PDF in some of its errors.
        for name in filter(None, (file, Path(file).name)):
            error = error.replace(name, "the PDF")
        found.append(_error(f"the SIGSOFT checker could not read the PDF: {error}"))
        if not record.get("pages"):
            return found
    for issue in record.get("issues") or []:
        code = str(issue.get("code", "unknown"))
        if code.startswith("non-references-after"):
            code = "non-references-after-limit"
        severity = SEVERITY.get(code, Severity.WARNING)
        message = MESSAGES.get(code, code.replace("-", " "))
        found.append(Finding(f"sigsoft.{code}", severity, message, page=issue.get("page"),
                             evidence=str(issue.get("detail") or "")))
    return found


def _command(papers: list[Paper], profile: Profile, workdir: Path) -> list[str]:
    rules, anonymity = profile.format, profile.options("anonymity")
    command = [tools.program("java"), "-jar", str(tools.submission_checker()), "--json",
               "--style", rules.style, "--mainpages", str(rules.main_pages),
               # The joined form keeps a pattern that starts with a dash, such as -paper(\d+), from reading as an option.
               "--refpages", str(rules.reference_pages), f"--id-pattern={profile.file_pattern}"]
    authors = _write_authors(papers, workdir)
    if authors:
        command += ["--meta", str(authors)]
    hosts = anonymity.get("allowed_hosts") or []
    if hosts:
        command += ["--allowed-hosts", ",".join(hosts)]
    if anonymity.get("flag_acknowledgments", True):
        command.append("--flag-acknowledgments")
    return command


def _write_authors(papers: list[Paper], workdir: Path) -> Path | None:
    rows = [(paper.paper_id, paper.title, a.first, a.last, a.email, a.affiliation)
            for paper in papers for a in paper.authors]
    if not rows:
        return None
    workdir.mkdir(parents=True, exist_ok=True)
    path = workdir / "sigsoft-authors.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["paper", "title", "first", "last", "email", "affiliation"])
        writer.writerows(rows)
    return path


def _check(command: list[str], papers: list[Paper], timeout: float) -> tuple[dict[int, list[Finding]], list[Paper]]:
    """Run the checker on papers and return the findings of each paper and the papers that got no record."""
    records, reason = _run(command, papers, timeout)
    by_name = {paper.pdf.name: paper.paper_id for paper in papers}
    results = {}
    for record in records:
        paper_id = by_name.get(Path(str(record.get("file", ""))).name)
        if paper_id is not None:
            results[paper_id] = findings(record)
    missing = [paper for paper in papers if paper.paper_id not in results]
    message = f"no result from the SIGSOFT checker: {reason}" if reason else "no result from the SIGSOFT checker"
    results.update({paper.paper_id: [_error(message)] for paper in missing})
    return results, missing


def _run(command: list[str], papers: list[Paper], timeout: float) -> tuple[list[dict], str]:
    """Run the checker on the PDFs of papers and return its records and, if it stopped early, the reason."""
    # An absolute path keeps a file name that starts with a dash from reading as an option.
    pdfs = [str(paper.pdf.absolute()) for paper in papers]
    try:
        result = subprocess.run(command + pdfs, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                check=False, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout.decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else exc.stdout or ""
        return _records(output), f"it did not finish within {timeout:g} seconds"
    if result.returncode == 0:
        return _records(result.stdout), ""
    return _records(result.stdout), _reason(result.stderr, result.returncode)


def _records(output: str) -> list[dict]:
    records = []
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def _reason(stderr: str, returncode: int) -> str:
    """Say in a few words why the checker stopped, naming no path or file, which its messages may hold."""
    if "OutOfMemoryError" in stderr:
        return "it ran out of memory"
    if returncode == USAGE_ERROR:
        return "it rejected its arguments"
    thrown = JAVA_EXCEPTION.search(stderr)
    return f"it stopped with {thrown.group(1)}" if thrown else f"it stopped with exit code {returncode}"


def _error(message: str) -> Finding:
    return Finding("sigsoft.error", Severity.WARNING, message)

"""Anonymity and template check with the SIGSOFT submission checker, revised for PeerCheck.

The SIGSOFT submission checker was built for ICSE 2021 and reads each PDF with PDFBox. The revised jar
under peercheck/vendor scans every page, the metadata, and the links of a PDF for the authors of the
paper, author emails, links that point to a person, acknowledgments, and self-citations, and prints one
JSON object per PDF. Options come from the profile: style, page limits, and file pattern from the format
rules, and allowed_hosts and flag_acknowledgments under checks.anonymity.
"""

from __future__ import annotations

import csv
import json
import subprocess
from pathlib import Path

from peercheck import tools
from peercheck.findings import Finding, Severity
from peercheck.models import Paper
from peercheck.profile import Profile

SECONDS_PER_PAPER = 60
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
    """Run the checker once over all papers and return the findings of each paper."""
    if not papers:
        return {}
    command = _command(papers, profile, workdir)
    by_name = {paper.pdf.name: paper.paper_id for paper in papers}
    results = {paper.paper_id: [] for paper in papers}
    try:
        output = _run(command + [str(paper.pdf) for paper in papers], len(papers))
    except (subprocess.SubprocessError, OSError, tools.ToolError) as exc:
        return {paper.paper_id: [_error(str(exc))] for paper in papers}
    seen = set()
    for record in output:
        paper_id = by_name.get(Path(str(record.get("file", ""))).name)
        if paper_id is None:
            continue
        seen.add(paper_id)
        results[paper_id] = findings(record)
    for paper_id in set(results) - seen:
        results[paper_id] = [_error("no result from the SIGSOFT checker")]
    return results


def check(paper: Paper, profile: Profile, workdir: Path) -> list[Finding]:
    """Return the findings of the checker for one paper."""
    return check_batch([paper], profile, workdir)[paper.paper_id]


def findings(record: dict) -> list[Finding]:
    """Turn one JSON record of the checker into findings, keeping the issues of a PDF that opened."""
    found = []
    if record.get("error"):
        found.append(_error(f"the SIGSOFT checker could not read the PDF: {record['error']}"))
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
               "--refpages", str(rules.reference_pages), "--id-pattern", profile.file_pattern]
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


def _run(command: list[str], count: int) -> list[dict]:
    result = subprocess.run(command, capture_output=True, text=True, check=False,
                            timeout=SECONDS_PER_PAPER * max(count, 1))
    records = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    if result.returncode != 0 and not records:
        detail = next((x for x in result.stderr.splitlines() if x.strip()), f"exit code {result.returncode}")
        raise subprocess.SubprocessError(f"the SIGSOFT checker failed: {detail}")
    return records


def _error(message: str) -> Finding:
    return Finding("sigsoft.error", Severity.WARNING, message)

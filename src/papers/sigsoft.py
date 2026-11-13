"""Anonymity and template check with the SIGSOFT submission checker, revised for PeerCheck.

The SIGSOFT submission checker was built for ICSE 2021 and reads each PDF with PDFBox. The revised jar
in external/submission-checker scans every page, the metadata, and the links of a PDF for the authors of the
paper, author emails, links that point to a person, acknowledgments, and self-citations, and prints one
JSON object per PDF. Options come from the profile: style, page limits, and file pattern from the format
rules, and allowed_hosts and flag_acknowledgments under checks.anonymity. The findings give each name of the
metadata once and the links to one repository as one finding.
"""

from __future__ import annotations

import csv
import dataclasses
import json
import re
import shutil
import subprocess
from pathlib import Path

from peercheck import tools
from peercheck.findings import Finding, Severity
from peercheck.models import Paper
from peercheck.profile import Profile

SECONDS_PER_PAPER = 60
# The checker reads the paper number from the file name of each PDF, as the names of its links give it.
LINK_PATTERN = r"paper(\d+)\.pdf$"
# The exit status of the checker when it rejects its arguments, such as a file it cannot find.
USAGE_ERROR = 2
JAVA_EXCEPTION = re.compile(r'Exception in thread "[^"]*" ([\w.$]+)')
META_AUTHOR, IDENTITY_DATA, IDENTITY_LINK = (
    "possibly-author-revealing-meta-data", "possibly-identity-revealing-data", "identity-link")
# The kind that the checker gives a link to an account or a repository, Kind.CODE_HOST_ACCOUNT in LinkClassifier.java.
CODE_HOST_ACCOUNT = "code host account"
# A detail of the checker with its place or kind in parentheses, such as Lena Brandt (XMP dc:creator).
LABELED = re.compile(r"(.*?) \(((?:[^()]|\([^()]*\))*)\)")
# The signs between the names of one metadata string, such as Lena Brandt; Omar Haddad.
NAME_SEPARATOR = re.compile(r"\s*(?:[;,&]|\band\b)\s*")
# The start of a link that linkKey in PdfChecker.java drops before it compares two links.
LINK_START = re.compile(r"^(?:[a-z][a-z0-9+.-]*://)?(?:www\.)?")
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
    papers = _linked(papers, workdir)
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
    for issue in _merged(record.get("issues") or []):
        code = str(issue.get("code", "unknown"))
        if code.startswith("non-references-after"):
            code = "non-references-after-limit"
        severity = SEVERITY.get(code, Severity.WARNING)
        message = MESSAGES.get(code, code.replace("-", " "))
        found.append(Finding(f"sigsoft.{code}", severity, message, page=issue.get("page"),
                             evidence=str(issue.get("detail") or "")))
    return found


def _merged(issues: list[dict]) -> list[dict]:
    """Return the issues with one issue for the names that one place of the metadata gives and one for the links to
    one repository or host. A name that another issue gives is left out."""
    names = [text for issue in issues if issue.get("code") == IDENTITY_DATA
             for text, label in [_labeled(issue)] if label]
    merged: dict[object, dict] = {}
    for number, issue in enumerate(issues):
        code = issue.get("code")
        text, label = _labeled(issue)
        if code == META_AUTHOR:
            if _repeats(text, names):
                continue
            names.append(text)
            key = (code, label)
        elif code == IDENTITY_LINK:
            key = (code, label, _link_group(text, label))
        else:
            merged[number] = issue
            continue
        group = merged.setdefault(key, {"code": code, "page": issue.get("page"), "texts": [], "label": label})
        group["texts"].append(text)
    for issue in merged.values():
        if "texts" in issue:
            issue["detail"] = _joined(issue["code"], issue["texts"], issue["label"])
    return list(merged.values())


def _labeled(issue: dict) -> tuple[str, str]:
    """Split the detail of an issue into its text and the label in parentheses that may follow it."""
    detail = str(issue.get("detail") or "")
    match = LABELED.fullmatch(detail)
    return (match[1], match[2]) if match else (detail, "")


def _joined(code: str, texts: list[str], label: str) -> str:
    """Return the detail of merged issues: every name, or the first link with the number of the other links."""
    if code == META_AUTHOR:
        text = "; ".join(texts)
    else:
        text = texts[0] + (f" and {len(texts) - 1} more" if len(texts) > 1 else "")
    return f"{text} ({label})" if label else text


def _repeats(name: str, names: list[str]) -> bool:
    """Tell whether each name of a metadata string stands in a name that another issue gives, whatever its case."""
    parts = [part for part in NAME_SEPARATOR.split(name.casefold()) if part]
    return bool(parts) and all(any(_holds(other.casefold(), part) for other in names) for part in parts)


def _holds(text: str, words: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(words)}(?!\w)", text) is not None


def _link_group(link: str, kind: str) -> str:
    """Return the host of a link, and for a code host also the account and the repository."""
    host, *path = LINK_START.sub("", link.strip().lower()).split("/")
    return "/".join([host, *path[:2]]) if kind == CODE_HOST_ACCOUNT else host


def _command(papers: list[Paper], profile: Profile, workdir: Path) -> list[str]:
    rules, anonymity = profile.format, profile.options("anonymity")
    command = [tools.program("java"), "-jar", str(tools.submission_checker()), "--json",
               "--style", rules.style, "--mainpages", str(rules.main_pages),
               "--refpages", str(rules.reference_pages), f"--id-pattern={LINK_PATTERN}"]
    authors = _write_authors(papers, workdir)
    if authors:
        command += ["--meta", str(authors)]
    hosts = anonymity.get("allowed_hosts") or []
    if hosts:
        command += ["--allowed-hosts", ",".join(hosts)]
    if anonymity.get("flag_acknowledgments", True):
        command.append("--flag-acknowledgments")
    return command


def _linked(papers: list[Paper], workdir: Path) -> list[Paper]:
    """Return the papers with a link to each PDF that is named for the paper number, the name the checker reads."""
    folder = workdir / "sigsoft-pdfs"
    folder.mkdir(parents=True, exist_ok=True)
    linked = []
    for paper in papers:
        link = folder / f"paper{paper.paper_id}.pdf"
        link.unlink(missing_ok=True)
        try:
            link.symlink_to(paper.pdf.absolute())
        except OSError:
            # A file system without symbolic links, such as one of Windows, gets a copy.
            shutil.copyfile(paper.pdf, link)
        linked.append(dataclasses.replace(paper, pdf=link))
    return linked


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

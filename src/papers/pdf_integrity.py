"""Encryption, permissions, and damaged structure of a submission PDF, found with PyMuPDF and pikepdf."""

from __future__ import annotations

import io
import re
from pathlib import Path

import pikepdf
import pymupdf

from peercheck.findings import Finding, Severity
from peercheck.models import Paper
from peercheck.profile import Profile

# Permission bits with the same meaning in every revision of the standard security handler.
PERMISSIONS = (
    (pymupdf.PDF_PERM_PRINT, "printing"),
    (pymupdf.PDF_PERM_MODIFY, "editing"),
    (pymupdf.PDF_PERM_COPY, "copying text"),
    (pymupdf.PDF_PERM_ANNOTATE, "adding comments"),
)
# Reviewers print, quote, and annotate a paper; a ban on editing alone never reaches them.
REVIEWER_PERMISSIONS = pymupdf.PDF_PERM_PRINT | pymupdf.PDF_PERM_COPY | pymupdf.PDF_PERM_ANNOTATE
EXAMPLES = 3
# The object and the offset that qpdf names after the file and before its message.
QPDF_PLACE = re.compile(r"^(?:[ ,][^:]*)?: ")


def check(paper: Paper, profile: Profile, workdir: Path) -> list[Finding]:
    """Return an error for a PDF that needs a password or does not open, and notes on its permissions and structure."""
    try:
        data = Path(paper.pdf).read_bytes()
    except OSError as exc:
        return [_unreadable(f"The PDF cannot be read ({exc.strerror or type(exc).__name__}).")]
    if not data:
        return [_unreadable("The PDF file is empty.")]
    # Both libraries read the bytes, which keeps the path of the file out of their messages.
    try:
        document = pymupdf.open(stream=data, filetype="pdf")
    except (RuntimeError, pymupdf.mupdf.FzErrorBase):
        return [_unreadable("The file does not open as a PDF, even after repair.")]
    with document:
        if document.needs_pass:
            return [Finding("pdf.password", Severity.ERROR,
                            "The PDF needs a password to open, so no other check can read it.")]
        if not document.page_count:
            return [_unreadable("The PDF opens without a readable page.")]
        findings = _encryption(document)
        repaired = document.is_repaired
    problems = _syntax_problems(data)
    if repaired or problems:
        findings.append(_damage(repaired, problems))
    return findings


def _syntax_problems(data: bytes) -> list[str]:
    """Return the syntax and structure problems that qpdf finds in the bytes of a PDF, without the name of the file."""
    stream = io.BytesIO(data)
    # pikepdf names a stream by this text in each of its messages.
    name = f"stream {stream}"
    try:
        with pikepdf.open(stream) as pdf:
            problems = pdf.check_pdf_syntax()
    except pikepdf.PikepdfError as exc:
        problems = [str(exc)]
    return [QPDF_PLACE.sub("", problem.removeprefix("WARNING: ").replace(name, "", 1)) for problem in problems]


def _encryption(document: pymupdf.Document) -> list[Finding]:
    """Return a warning for restrictions that reviewers notice, or info for a PDF that is encrypted without them."""
    if not (document.metadata or {}).get("encryption"):
        return []
    granted = document.permissions
    denied = [name for bit, name in PERMISSIONS if not granted & bit]
    if REVIEWER_PERMISSIONS & ~granted:
        return [Finding("pdf.permissions", Severity.WARNING, f"An owner password of the PDF forbids {_join(denied)}.")]
    forbids = f" and forbids {_join(denied)}" if denied else ""
    return [Finding("pdf.encrypted", Severity.INFO, f"The PDF is encrypted but opens without a password{forbids}.")]


def _damage(repaired: bool, problems: list[str]) -> Finding:
    """Return the info note for a PDF that MuPDF had to repair or in which qpdf finds problems."""
    causes = ["MuPDF had to repair it on opening"] if repaired else []
    if problems:
        causes.append(f"qpdf reports {len(problems)} {'problem' if len(problems) == 1 else 'problems'}")
    examples = list(dict.fromkeys(problems))[:EXAMPLES]
    return Finding("pdf.damaged", Severity.INFO, f"The PDF structure is damaged: {' and '.join(causes)}.",
                   evidence=" | ".join(examples))


def _unreadable(message: str) -> Finding:
    return Finding("pdf.unreadable", Severity.ERROR, message)


def _join(items: list[str]) -> str:
    if len(items) < 3:
        return " and ".join(items)
    return f"{', '.join(items[:-1])}, and {items[-1]}"

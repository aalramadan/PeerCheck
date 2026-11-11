"""Line numbers of a submission PDF, as the review option of acmart and the lineno package print them, for a venue whose
profile expects them. A page counts as numbered when a column of numbers beside its text counts up from line to line,
as in the line count of the SIGSOFT submission checker."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from peercheck.findings import Finding, Severity
from peercheck.models import Paper
from peercheck.profile import Profile, ProfileError

CHECK = "line-numbers"
OPTIONS = "line_numbers"
POLICIES = {"ignore": None, "info": Severity.INFO, "warning": Severity.WARNING, "error": Severity.ERROR}
NUMBER = re.compile(r"[0-9]{1,5}")
# acmart prints 49 to 58 numbers per column, and lineno with \modulolinenumbers[5] about ten.
MIN_LINE_NUMBERS = 8
ALIGNMENT = 1.0
# Line numbers run along most of the text of a page, while a numbered listing covers a part of it.
MIN_COVERAGE = 0.5
READ_ERRORS = (OSError, RuntimeError, ValueError, pymupdf.mupdf.FzErrorBase)


@dataclass(frozen=True)
class Word:
    """A word of a page with its box."""

    x0: float
    y0: float
    x1: float
    y1: float
    text: str


def check(paper: Paper, profile: Profile, workdir: Path) -> list[Finding]:
    """Return a finding if fewer than half of the pages carry line numbers at a venue whose profile expects them.

    missing (default ignore): the severity of the finding, one of ignore, info, warning, and error.
    """
    policy = str(profile.options(OPTIONS).get("missing", "ignore")).lower()
    if policy not in POLICIES:
        raise ProfileError(f"checks.{OPTIONS}.missing must be one of {', '.join(POLICIES)}")
    severity = POLICIES[policy]
    if severity is None:
        return []
    # The integrity check reports a PDF that does not open or that needs a password.
    try:
        document = pymupdf.open(paper.pdf)
    except READ_ERRORS:
        return []
    pages = numbered = 0
    with document:
        if document.needs_pass:
            return []
        for page in document:
            try:
                numbered += _numbered_page(page)
            except READ_ERRORS:
                continue
            pages += 1
    if 2 * numbered >= pages:
        return []
    noun = "page" if pages == 1 else "pages"
    message = f"line numbers on {numbered} of {pages} {noun}, expected line numbers on every page"
    return [Finding(f"{CHECK}.missing", severity, message)]


def _numbered_page(page: pymupdf.Page) -> bool:
    """Return True if a column of line numbers runs beside the text along most of the page."""
    words = [Word(*word[:5]) for word in page.get_text("words")]
    if not words:
        return False
    height = max(word.y1 for word in words) - min(word.y0 for word in words)
    numbers = [word for word in words if NUMBER.fullmatch(word.text)]
    for edge in ("x0", "x1"):
        for column in _columns(numbers, edge):
            if any(len(run) >= MIN_LINE_NUMBERS and run[-1].y1 - run[0].y0 >= MIN_COVERAGE * height
                   for run in _runs(column)) and _apart(column, words):
                return True
    return False


def _columns(words: list[Word], edge: str) -> list[list[Word]]:
    """Group the words whose left or right edges line up, each group from top to bottom."""
    columns: list[list[Word]] = []
    for word in sorted(words, key=lambda word: getattr(word, edge)):
        if columns and getattr(word, edge) - getattr(columns[-1][0], edge) <= ALIGNMENT:
            columns[-1].append(word)
        else:
            columns.append([word])
    return [sorted(column, key=lambda word: word.y0) for column in columns]


def _runs(column: list[Word]) -> list[list[Word]]:
    """Split a column of numbers, from top to bottom, into runs that count up by a fixed step."""
    runs: list[list[Word]] = []
    for word in column:
        run = runs[-1] if runs else []
        step = int(run[1].text) - int(run[0].text) if len(run) > 1 else None
        rise = int(word.text) - int(run[-1].text) if run else 0
        if rise > 0 and step in (None, rise):
            run.append(word)
        else:
            runs.append([word])
    return runs


def _apart(column: list[Word], words: list[Word]) -> bool:
    """Return True if no other word of the page reaches into the band of the column, as text and tables do."""
    left, right = min(word.x0 for word in column), max(word.x1 for word in column)
    members = set(column)
    return not any(word.x0 < right and word.x1 > left for word in words if word not in members)

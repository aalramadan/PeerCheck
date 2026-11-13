"""Line numbers of a submission PDF, as the review option of acmart and the lineno package print them, for a venue whose
profile expects them. A page counts as numbered when a column of numbers beside its text counts up from line to line,
as in the line count of the SIGSOFT submission checker."""

from __future__ import annotations

import itertools
import re
from collections.abc import Callable
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
# lineno and acmart set every line number in one font, so the boxes of the numbers of a count are one height.
SAME_FONT = 0.5
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
    pages: list[list[Word]] = []
    unread = 0
    with document:
        if document.needs_pass:
            return []
        for page in document:
            try:
                pages.append([Word(*word[:5]) for word in page.get_text("words")])
            except READ_ERRORS:
                pages.append([])
                unread += 1
    counts = [line_counts(words) for words in pages]
    numbered = sum(_numbered_page(words, counts, number) for number, words in enumerate(pages))
    readable = len(pages) - unread
    if 2 * numbered >= readable:
        return []
    noun = "page" if readable == 1 else "pages"
    message = f"line numbers on {numbered} of {readable} {noun}, expected line numbers on every page"
    return [Finding(f"{CHECK}.missing", severity, message)]


def _numbered_page(words: list[Word], counts: list[list[list[Word]]], number: int) -> bool:
    """Return True if a column of line numbers runs beside the text along most of a page, given its words, the counts
    of every page, and its index."""
    if not words:
        return False
    height = max(word.y1 for word in words) - min(word.y0 for word in words)
    return any(_extent(count) >= MIN_COVERAGE * height for _before, count in _chains(counts.__getitem__, number))


def _extent(count: list[Word]) -> float:
    """Return the height of the tallest column of a count, which runs down a column and goes on atop the next."""
    tops = [index for index in range(1, len(count)) if count[index].y0 < count[index - 1].y0]
    return max(count[last - 1].y1 - count[first].y0 for first, last in itertools.pairwise([0, *tops, len(count)]))


def number_runs(words: list[Word]) -> list[list[Word]]:
    """Return each run of numbers that stands beside the text of a page and counts up from line to line."""
    return [count for count in line_counts(words) if len(count) >= MIN_LINE_NUMBERS]


def continued_runs(counts: Callable[[int], list[list[Word]]], page: int) -> list[list[Word]]:
    """Return each run of numbers of a page as number_runs does, behind the numbers of the pages before that it goes
    on from, if any. The first argument returns the line_counts of a page by its index.

    lineno counts the lines through the whole document, so a run of fewer than MIN_LINE_NUMBERS numbers, as in a last
    column or with \\modulolinenumbers, counts when it goes on with the count of the page before."""
    return [before + count for before, count in _chains(counts, page)]


def _chains(counts: Callable[[int], list[list[Word]]], page: int) -> list[tuple[list[Word], list[Word]]]:
    """Return each count of a page that holds at least MIN_LINE_NUMBERS numbers, by itself or with the numbers of the
    pages before that it goes on from, as these numbers and the count."""
    chains = []
    for count in counts(page):
        before: list[Word] = []
        earlier = page
        while len(before) + len(count) < MIN_LINE_NUMBERS and earlier > 0:
            earlier -= 1
            ahead = next((other for other in counts(earlier) if _goes_on(before + count, other)), None)
            if ahead is None:
                break
            before = ahead + before
        if len(before) + len(count) >= MIN_LINE_NUMBERS:
            chains.append((before, count))
    return chains


def line_counts(words: list[Word]) -> list[list[Word]]:
    """Return each count of a page: the runs of numbers apart from the text that count on from column to column, and
    with a count of at least MIN_LINE_NUMBERS such numbers the runs before and after it that text reaches.

    lineno counts the lines of a page through its columns. In two columns it prints the numbers of one column in the
    gutter, where the lines of the other column reach them: the right column without an option, the left with right."""
    numbers = [word for word in words if NUMBER.fullmatch(word.text)]
    apart: list[list[Word]] = []
    reached: list[list[Word]] = []
    for edge in ("x0", "x1"):
        for column in _columns(numbers, edge):
            (apart if _apart(column, words) else reached).extend(_runs(column))
    counts: list[list[Word]] = []
    for run in sorted(apart, key=_first):
        before = next((count for count in counts if _goes_on(run, count)), None)
        if before is None:
            counts.append(list(run))
        else:
            before.extend(run)
    proven = [count for count in counts if len(count) >= MIN_LINE_NUMBERS]
    if proven:
        _join_reached(proven, reached)
    return counts


def _join_reached(counts: list[list[Word]], runs: list[list[Word]]) -> None:
    """Put each run that text reaches behind the count that it goes on from, or before the count that goes on from
    it."""
    for run in sorted(runs, key=_first):
        before = next((count for count in counts if _goes_on(run, count)), None)
        if before is not None:
            before.extend(run)
    for run in sorted(runs, key=_first, reverse=True):
        after = next((count for count in counts if _goes_on(count, run)), None)
        if after is not None:
            after[:0] = run


def _first(run: list[Word]) -> int:
    """Return the number that a run starts with."""
    return int(run[0].text)


def _goes_on(run: list[Word], before: list[Word]) -> bool:
    """Return True if a run goes on with the count of the run before it, by the step of the two and in its font."""
    steps = {int(pair[1].text) - int(pair[0].text) for pair in (run[:2], before[-2:]) if len(pair) == 2}
    return (len(steps) == 1 and int(run[0].text) - int(before[-1].text) in steps
            and abs((run[0].y1 - run[0].y0) - (before[-1].y1 - before[-1].y0)) < SAME_FONT)


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
    return not any(word.x0 < right and word.x1 > left and word not in members for word in words)

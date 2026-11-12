"""Title of a submission PDF against the title of the submissions file, compared as by the metadata checker of
aclpubcheck, to find a PDF that belongs to another paper. The title of the PDF is its largest text on page 1, with the
metadata Title as a fallback."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pymupdf
from rapidfuzz import fuzz

from peercheck.dblp import fold
from peercheck.findings import Finding, Severity
from peercheck.models import Paper
from peercheck.profile import Profile

CHECK = "title"
# Of 135 hand-labeled pairs of an ICSE, FSE, or ASE title and a CoRR title by the same authors in dblp, a token set
# ratio below 70 flags 83 of 97 pairs of two papers and 8 of 38 pairs of one paper under a revised title.
SIMILARITY_MIN = 70
HEAD_CHARACTERS = 500
# A title of the submissions file of fewer words, such as TBD, may stand inside any text.
HEAD_MIN_WORDS = 3
# Text within this many points counts as one size, as in the fonts check.
SIZE_RANGE = 0.5
# The title needs this many letters, which leaves out a drop cap, a lone symbol, and a column of line numbers.
MIN_LETTERS = 4
# Small capitals faked with smaller letters reach 80% of the size of the capitals, and line numbers stay below 45%.
SMALL_CAPS = 0.6
READ_ERRORS = (OSError, RuntimeError, ValueError, pymupdf.mupdf.FzErrorBase)
LATEX_COMMAND = re.compile(r"\\[A-Za-z]+")
# The mark between a title and its subtitle, such as a colon or a dash.
SUBTITLE = re.compile(r"\s*(?::|\?|!|\u2014|\u2013|\s-\s|\.\s)\s*")


@dataclass(frozen=True)
class Line:
    """A horizontal line of text on a page, with the size and the text of each of its spans."""

    top: float
    left: float
    spans: tuple[tuple[float, str], ...]

    @property
    def text(self) -> str:
        """Return the text of the whole line."""
        return "".join(text for _, text in self.spans)


def check(paper: Paper, profile: Profile, workdir: Path) -> list[Finding]:
    """Return a warning if the title of the PDF differs from the title of the submissions file.

    similarity_min (default 70): the rapidfuzz token set ratio of the two titles, from 0 to 100, below which titles
    that differ in more than case, punctuation, line breaks, and a subtitle give the warning.
    """
    sheet = paper.title.strip()
    if not _letters(sheet):
        return []
    minimum = float(profile.options(CHECK).get("similarity_min", SIMILARITY_MIN))
    # The integrity check reports a PDF that does not open or that needs a password.
    try:
        document = pymupdf.open(paper.pdf)
    except READ_ERRORS:
        return []
    with document:
        if document.needs_pass or not document.page_count:
            return []
        try:
            lines = _lines(document[0])
        except READ_ERRORS:
            lines = []
        metadata = str((document.metadata or {}).get("title") or "")
    candidates = [(source, title) for source, title in (("title on page 1", _largest_text(lines)),
                                                        ("metadata title", metadata))
                  if _letters(title) >= MIN_LETTERS]
    if not candidates:
        return [Finding(f"{CHECK}.not-found", Severity.INFO,
                        "no title on page 1 or in the metadata to compare with the submissions file")]
    if any(same_title(sheet, title) for _, title in candidates) or _in_head(sheet, lines):
        return []
    score, source = max((similarity(sheet, title), source) for source, title in candidates)
    if score >= minimum:
        return []
    message = (f"{source} differs from the title in the submissions file (similarity {score:.0f} of 100, expected "
               f"{minimum:g} or more)")
    return [Finding(f"{CHECK}.mismatch", Severity.WARNING, message, 1 if source == "title on page 1" else None)]


def same_title(sheet: str, title: str) -> bool:
    """Return True if two titles differ at most in case, punctuation, spacing, line breaks, and a subtitle."""
    first, second = _squash(sheet), _squash(title)
    if first == second:
        return True
    shorter, longer = (sheet, title) if len(first) < len(second) else (title, sheet)
    part = _squash(shorter)
    return bool(part) and any(_squash(longer[:mark.start()]) == part or _squash(longer[mark.end():]) == part
                              for mark in SUBTITLE.finditer(longer))


def similarity(sheet: str, title: str) -> float:
    """Return the rapidfuzz token set ratio of the words of two titles, from 0 to 100."""
    return fuzz.token_set_ratio(_words(sheet), _words(title))


def _lines(page: pymupdf.Page) -> list[Line]:
    """Return the horizontal lines of a page that hold a letter, from the top of the page down."""
    lines = []
    for block in page.get_text("dict", flags=pymupdf.TEXTFLAGS_TEXT)["blocks"]:
        for line in block.get("lines", ()):
            # A stamp or a watermark runs at an angle.
            if line["dir"][0] < 0.99:
                continue
            spans = tuple((span["size"], span["text"]) for span in line["spans"])
            if any(_letters(text) for _, text in spans):
                lines.append(Line(round(line["bbox"][1], 1), line["bbox"][0], spans))
    return sorted(lines, key=lambda line: (line.top, line.left))


def _largest_text(lines: list[Line]) -> str:
    """Return the lines with the largest letters, from the top, once they hold at least MIN_LETTERS letters.

    A line keeps its spaces and its letters down to SMALL_CAPS of the largest size, as in a title set in small capitals.
    """
    sizes = sorted({size for line in lines for size, text in line.spans if _letters(text)}, reverse=True)
    for size in sizes:
        parts = ["".join(text for span, text in line.spans if span >= SMALL_CAPS * size or not text.strip())
                 for line in lines if any(abs(span - size) <= SIZE_RANGE and _letters(text) for span, text in line.spans)]
        title = " ".join(" ".join(parts).split())
        if _letters(title) >= MIN_LETTERS:
            return title
    return ""


def _in_head(sheet: str, lines: list[Line]) -> bool:
    """Return True if the listed title stands in the first characters of the page, as aclpubcheck looks for it."""
    if len(_words(sheet).split()) < HEAD_MIN_WORDS:
        return False
    head = " ".join(line.text for line in lines)[:HEAD_CHARACTERS]
    return _squash(sheet) in _squash(head)


def _words(text: str) -> str:
    """Return the words of a title in lowercase ASCII, without LaTeX commands such as \\textsc."""
    return fold(LATEX_COMMAND.sub(" ", text))


def _squash(text: str) -> str:
    return _words(text).replace(" ", "")


def _letters(text: str) -> int:
    return sum(char.isalpha() for char in text)

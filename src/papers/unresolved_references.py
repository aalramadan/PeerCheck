"""Marks of a lost cross-reference in the text of a submission PDF: ?? or [?] from an incomplete LaTeX build and the
error text that Word prints.

A LaTeX mark counts as a bold run of its own, as LaTeX sets it, or as ?? after a word such as Section or Fig.
"""

from __future__ import annotations

import re
from pathlib import Path

import pymupdf

from peercheck.findings import Finding, Severity
from peercheck.models import Paper
from peercheck.profile import Profile

EXAMPLES = 3
CONTEXT = 30
# LuaLaTeX with OpenType Libertine sets ?? as the ligature U+2047.
LIGATURES = {"\u2047": "??"}
# A bold run of nothing but question marks, such as ?? for \ref, ? for \cite, or ? ? for two citations of natbib.
MARK_RUN = re.compile(r"\?+(?:[\s,;]+\?+)*")
QUESTION_MARKS = re.compile(r"\?+")
MARK_CHARACTERS = re.compile("[?" + "".join(LIGATURES) + "]")
# Word prints this text in place of a cross-reference or a bookmark that no longer exists.
WORD_ERROR = re.compile(r"Error! (?:Reference source not found|Bookmark not defined)")
# ?? after a word that opens a cross-reference, in any type, as in Section ??, Fig.??, Eq. (??), or RQ??. The plural
# pages and pp. stay out, since a reference list may give the pages of a work to appear as pp. ??.
WORD_MARK = re.compile(
    r"(?:\b(?:sections?|figures?|tables?|equations?|algorithms?|listings?|appendix|appendices|chapters?|theorems?|"
    r"lemmas?|definitions?|corollary|propositions?|lines?|page|footnotes?)[\s~]+"
    r"|\b(?:secs?|figs?|tabs?|eqs?|algs?|lst|app|chap|thm|defs?|prop|p)\.[\s~]*|\bRQ[\s~]*|§[\s~]*)\(?(\?\?)(?!\?)",
    re.IGNORECASE,
)


def check(paper: Paper, profile: Profile, workdir: Path) -> list[Finding]:
    """Return one info note that counts the marks of undefined references and citations and names their pages."""
    marks = []
    # The integrity check reports a PDF that does not open or that needs a password.
    try:
        document = pymupdf.open(paper.pdf)
    except (OSError, RuntimeError, ValueError, pymupdf.mupdf.FzErrorBase):
        return []
    with document:
        if document.needs_pass:
            return []
        for number, page in enumerate(document, start=1):
            try:
                marks += [(number, text, start, end) for text, start, end in _page_marks(page)]
            except (RuntimeError, ValueError, pymupdf.mupdf.FzErrorBase):
                continue
    if not marks:
        return []
    examples, lines = [], set()
    for number, text, start, end in marks:
        if (number, text) not in lines and len(examples) < EXAMPLES:
            lines.add((number, text))
            examples.append(f"page {number}: {_excerpt(text, start, end)}")
    noun = "mark" if len(marks) == 1 else "marks"
    pages = _pages(sorted({number for number, *_ in marks}))
    message = f"{len(marks)} {noun} of undefined references or citations, such as ?? or [?], on {pages}."
    return [Finding("unresolved.marks", Severity.INFO, message, evidence=" | ".join(examples))]


def _page_marks(page: pymupdf.Page) -> list[tuple[str, int, int]]:
    """Return the text of the line or the paragraph, the start, and the end of each mark on a page."""
    marks = []
    for block in page.get_text("dict", flags=pymupdf.TEXTFLAGS_TEXT)["blocks"]:
        lines = block.get("lines", [])
        for line in lines:
            if not any(MARK_CHARACTERS.search(span["text"]) for span in line["spans"]):
                continue
            text, bold = _line_text(line)
            found = dict.fromkeys(_bold_marks(text, bold))
            found.update(dict.fromkeys(match.span(1) for match in WORD_MARK.finditer(text)))
            marks += [(text, start, end) for start, end in sorted(found)]
        marks += _word_errors(lines)
    return marks


def _word_errors(lines: list[dict]) -> list[tuple[str, int, int]]:
    """Return the text of the paragraph, the start, and the end of each error text of Word, which may wrap."""
    if not any("Error!" in span["text"] for line in lines for span in line["spans"]):
        return []
    text = " ".join("".join(span["text"] for span in line["spans"]).strip() for line in lines)
    return [(text, *match.span()) for match in WORD_ERROR.finditer(text)]


def _line_text(line: dict) -> tuple[str, list[bool]]:
    """Return the text of a line and, for each of its characters, whether its font is bold."""
    chars = []
    for span in line["spans"]:
        bold = bool(span["flags"] & pymupdf.TEXT_FONT_BOLD)
        chars += [(char, bold) for char in "".join(LIGATURES.get(c, c) for c in span["text"])]
    return "".join(char for char, _ in chars), [bold for _, bold in chars]


def _bold_marks(text: str, bold: list[bool]) -> list[tuple[int, int]]:
    """Return the question marks that form a bold run of their own, ?? anywhere and ? beside a bracket."""
    marks = []
    for start, end in _runs(bold):
        core = text[start:end].strip()
        if not MARK_RUN.fullmatch(core):
            continue
        offset = text.index(core, start)
        before, after = text[:offset].rstrip()[-1:], text[offset + len(core):].lstrip()[:1]
        # A lone bold ? outside brackets, as natbib sets for \citet, reads the same as a ? in a table or a figure.
        if "??" in core or before in ("[", "(") or after in ("]", ")"):
            marks += [(offset + match.start(), offset + match.end()) for match in QUESTION_MARKS.finditer(core)]
    return marks


def _runs(flags: list[bool]) -> list[tuple[int, int]]:
    """Return the start and the end of each run of true flags."""
    runs, start = [], None
    for index, flag in enumerate(flags + [False]):
        if flag and start is None:
            start = index
        elif not flag and start is not None:
            runs.append((start, index))
            start = None
    return runs


def _excerpt(text: str, start: int, end: int) -> str:
    left, right = max(0, start - CONTEXT), min(len(text), end + CONTEXT)
    excerpt = " ".join(text[left:right].split())
    return f"{'...' if left else ''}{excerpt}{'...' if right < len(text) else ''}"


def _pages(numbers: list[int]) -> str:
    """Name the pages in order, with three or more pages in a row as a range, such as pages 1 to 4 and 7."""
    if len(numbers) == 1:
        return f"page {numbers[0]}"
    parts, first = [], 0
    for index in range(1, len(numbers) + 1):
        if index == len(numbers) or numbers[index] != numbers[index - 1] + 1:
            run = numbers[first:index]
            parts += [f"{run[0]} to {run[-1]}"] if len(run) > 2 else [str(number) for number in run]
            first = index
    joined = " and ".join(parts) if len(parts) < 3 else f"{', '.join(parts[:-1])}, and {parts[-1]}"
    return f"pages {joined}"

"""Reads the reference list of a submission PDF as one entry per cited work.

The text of each page is rebuilt from its glyphs, since a PDF library may break a stretched line into single words,
run the words of a tight line together, and read the columns of a page in the order of the file. The list starts at
the last heading such as References and ends at an appendix, at text in another font size, or at the end of the
document. An entry starts at its label, such as [12] or 12., or at a line that hangs out to the left of the lines
below it. A caption, a footnote, or a biography in the font size of the list is left out by the place of its lines in
a labeled list, and by the rule above the footnotes in a list without labels.
"""

from __future__ import annotations

import itertools
import re
import statistics
import unicodedata
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from peercheck.papers import line_numbers

HEADING = re.compile(r"(?:\d{1,2}\.?|[IVX]{1,5}\.)?\s*(REFERENCES?(?:CITED)?|BIBLIOGRAPHY|LITERATURECITED|WORKSCITED"
                     r"|REFERENCESANDNOTES):?", re.IGNORECASE)
END_HEADING = re.compile(
    r"(?:(?:[A-Z]|\d{1,2}|[IVX]{1,5})\.?\s+)?(?:appendix|appendices|supplementa(?:ry|l)\b.*|acknowledge?ments?"
    r"|author\s+biograph(?:y|ies)|biograph(?:y|ies)|online\s+resources|artifact\s+appendix|received\s+\d)\b.{0,60}",
    re.IGNORECASE)
APPENDIX_SECTION = re.compile(r"[A-Z]\.?\s+[A-Z]\S*(?:\s+\S+){0,8}")
BRACKET_LABEL = re.compile(r"\[(\d{1,3})\]\s*")
DOTTED_LABEL = re.compile(r"(\d{1,3})\.\s+(?=\S)")
# Without the T1 font encoding, TeX draws an accent as a glyph of its own, which the text holds beside its letter or
# after the word.
ACCENTS = "`\u00b4\u02c6\u02dc\u00a8\u00af\u02d8\u02d9\u02da\u00b8\u02dd\u02db\u02c7"
ACCENT = re.compile(f"[{ACCENTS}]")
# The mark that joins a letter for each of the accents, in their order, and the letters that TeX prints without their
# dot below an accent.
COMBINING = dict(zip(ACCENTS, "\u0300\u0301\u0302\u0303\u0308\u0304\u0306\u0307\u030a\u0327\u030b\u0328\u030c"))
DOTLESS = {"\u0131": "i", "\u0237": "j"}
KEY_LABEL = re.compile(rf"\[(?:[^\W\d_]|[{ACCENTS}])[\w+\-{ACCENTS}]{{1,11}}\][{ACCENTS}]*\s*")
PAGE_NUMBER = re.compile(r"(?:page\s+)?\d{1,4}(?:\s*(?:of|/)\s*\d{1,4})?|[ivxl]{1,6}", re.IGNORECASE)
DIGITS = re.compile(r"\d+")
# The last word of a line that ends inside a link, a DOI, or an arXiv ID. url.sty may break a link after the colon
# of its scheme, and xurl inside the number of a DOI, which starts with 10 behind its label.
LINK_START = r"https?:|www\.|doi\.org/|\b10\.\d{4,9}/|doi:\s?1|arxiv:"
LINK_TAIL = re.compile(rf"(?:{LINK_START})\S*$", re.IGNORECASE)
LINK_HEAD = re.compile(LINK_START, re.IGNORECASE)
ARXIV_TAIL = re.compile(r"arxiv:\d{4}\.(\d{0,4})", re.IGNORECASE)
# A line that holds only the year of the entry or the day of a visit, as 2024-03-01, follows a whole link.
YEAR_LINE = re.compile(r"\(?(?:19|20)\d\d(?:[a-z]|-\d\d(?:-\d\d)?)?\)?[.,;]?")
# Without the T1 font encoding, TeX draws the underscore of a DOI as a rule, which leaves a gap in the text. A DOI
# of a book chapter at Springer ends in an underscore and the number of the chapter.
CHAPTER_DOI_GAP = re.compile(r"(\b10\.1007/[\d-]+[\dXx]) (?=\d{1,3}\b)")
# TeX breaks a link after one of these marks.
LINK_BREAKS = "/-_=?&%#~+"
OPENING, CLOSING = "([\u201c\u2018", ",.;:!?)]\u201d\u2019"
# A run of the page of this share of its height, from the top or from the bottom, may hold headers and footers.
EDGE_SHARE = 0.2
# Two glyphs stand a word apart when the gap between them exceeds this share of the font size.
WORD_GAP = 0.12
# TeX gives every word gap of a line one width, which in a tight line shrinks down to this share of the font size.
TIGHT_GAP = 0.04
TIGHT_GAPS = 3
# The word gaps of a tight line differ by less than this share of the font size, at least this part of them.
GAP_TOLERANCE = 0.005
ONE_WIDTH = 0.8
# A tight line shows at least this many narrow gaps for each wider gap, at no more than this share of its letters.
TIGHT_TO_WIDE = 3
TIGHT_SHARE = 0.34
SPACED_RUN = 3
# The reference list keeps one font size, and other text departs from it by more than this many points.
SIZE_TOLERANCE = 0.6
MIN_LABELS = 3
# A header or a footer stands at least this many points away from the text.
EDGE_GAP = 5.0
MIN_GUTTER = 6.0
WIDE_REACH = 30.0
# Spans stand on one line when their middles lie at most this share of the font size apart.
SAME_LINE = 0.4
# A page shows two columns by itself when at least this many lines stand on each side of the strip between them.
MIN_COLUMN_LINES = 3
# A footnote or a float below the lines of the list starts after a gap of this many line pitches.
BLOCK_GAP = 1.8
# An entry of the list starts this many points to the left of its further lines.
HANG = 3.0
# The last entry keeps at most this many lines, since text without a heading may follow the list.
MAX_ENTRY_LINES = 25
# Line numbers stand at most this many text lines apart for each step of their count, as the ruler of acmart does
# beside a list in small type, and the labels of a list at least two.
LINE_PITCH = 1.7
# The last entry keeps at most this many lines that follow a footnote or a float.
TAIL_LINES = 8
# A mark that sticks out of the margin or a space moves the start of a line by less than this share of the font size.
OFF_MARGIN = 0.5
# TeX fills every line of a justified entry but the last, so at most one such line in this many stops short, at a
# forced break or inside a link.
FORCED_BREAKS = 10
# TeX draws the rule above the footnotes 0.4 points thick, and LaTeX at most this share of the column wide.
RULE_HEIGHT = 1.0
RULE_SHARE = 0.5
READ_ERRORS = (OSError, RuntimeError, ValueError, pymupdf.mupdf.FzErrorBase)


@dataclass(frozen=True)
class Span:
    """A run of glyphs in one font on one baseline, with the left and the right edge of each glyph."""

    x0: float
    y0: float
    x1: float
    y1: float
    size: float
    text: str
    glyphs: tuple[tuple[str, float, float], ...]


@dataclass(frozen=True)
class NumberedPage:
    """The spans of a page, line numbers included, with the word and the counts that the line-number check sees."""

    spans: list[Span]
    words: list[line_numbers.Word]
    counts: list[list[line_numbers.Word]]


@dataclass(frozen=True)
class Line:
    """A text line of a page, in reading order, with its place and its main font size."""

    page: int
    column: int
    x0: float
    y0: float
    x1: float
    y1: float
    size: float
    text: str


@dataclass(frozen=True)
class Entry:
    """One entry of the reference list, without its label, as one line with a space at each line end of the page."""

    number: int
    text: str


def read(pdf: Path) -> list[Entry]:
    """Return the entries of the reference list of a PDF, or [] when the PDF shows no such list."""
    try:
        document = pymupdf.open(pdf)
    except READ_ERRORS:
        return []
    with document:
        try:
            if document.needs_pass:
                return []
            lines = _list_lines(document)
        except READ_ERRORS:
            return []
        return _entries(lines, document)


def _list_lines(document: pymupdf.Document) -> list[Line]:
    """Return the lines from the last reference heading to the end of the PDF, without headers and footers."""
    pages: dict[int, list[Line]] = {}
    layouts: dict[int, tuple[list[Span], float | None]] = {}
    numbered: dict[int, NumberedPage] = {}
    for number in range(len(document) - 1, -1, -1):
        pages[number] = _page_lines(document, number, layouts, numbered)
        start = next((i for i in range(len(pages[number]) - 1, -1, -1) if _is_heading(pages[number][i].text)), None)
        if start is not None:
            break
    else:
        return []
    for extra in (number - 1, number - 2):
        if extra >= 0:
            pages[extra] = _page_lines(document, extra, layouts, numbered)
    repeated = _repeated_edge_lines(pages, document[number].rect.height, (number, start))
    body = pages[number][start + 1:] + [line for later in range(number + 1, len(document)) for line in pages[later]]
    return [line for line in body if line not in repeated]


def _page_lines(document: pymupdf.Document, number: int, layouts: dict[int, tuple[list[Span], float | None]],
                numbered: dict[int, NumberedPage]) -> list[Line]:
    """Return the lines of a page, column by column, each rebuilt from the spans on one baseline."""
    spans, split = _layout(document, number, layouts, numbered)
    lines = []
    for column, members in enumerate(_columns(spans, split)):
        members.sort(key=_middle)
        row: list[Span] = []
        for span in members:
            if row and abs(_middle(span) - statistics.fmean(map(_middle, row))) > SAME_LINE * max(
                    other.size for other in [span, *row]):
                lines.append(_line(row, number, column))
                row = []
            row.append(span)
        if row:
            lines.append(_line(row, number, column))
    return lines


def _layout(document: pymupdf.Document, number: int, layouts: dict[int, tuple[list[Span], float | None]],
            numbered: dict[int, NumberedPage]) -> tuple[list[Span], float | None]:
    """Return the spans of a page and the middle of the gutter between its two columns, or None for one column.

    LaTeX sets the pages of a document in one layout. A page with too few lines to show its columns, such as the last
    page of a list, therefore takes the gutter of the page before it where its own text leaves that strip free."""
    undecided = []
    for page in range(number, -1, -1):
        if page in layouts:
            break
        spans = _without_line_numbers(document, page, numbered)
        strip = _free_strip(spans, document[page].rect)
        shown = strip is not None and _shows_columns(spans, *strip)
        layouts[page] = (spans, sum(strip) / 2 if shown else None)
        if shown or strip is None or page == 0:
            break
        undecided.append(page)
    for page in reversed(undecided):
        spans, before = layouts[page][0], layouts[page - 1][1]
        if before is not None and sum(span.x0 < before < span.x1 for span in spans) <= _may_cross(spans):
            layouts[page] = (spans, before)
    return layouts[number]


def _spans(page: pymupdf.Page) -> list[Span]:
    """Return the runs of glyphs of a page that hold text and run from left to right."""
    spans = []
    for block in page.get_text("rawdict", flags=pymupdf.TEXT_MEDIABOX_CLIP)["blocks"]:
        for line in block.get("lines", ()):
            if abs(line["dir"][0] - 1) > 0.01:
                continue
            for span in line["spans"]:
                glyphs = tuple((char["c"], char["bbox"][0], char["bbox"][2]) for char in span["chars"])
                text = "".join(glyph[0] for glyph in glyphs)
                if text.strip():
                    spans.append(Span(*span["bbox"], span["size"], text, glyphs))
    return spans


def _middle(span: Span) -> float:
    return (span.y0 + span.y1) / 2


def _without_line_numbers(document: pymupdf.Document, page: int, numbered: dict[int, NumberedPage]) -> list[Span]:
    """Return the spans of a page without the line numbers that a review version prints beside the text.

    Line numbers stand one line apart, while the bare labels of a numbered list stand one entry apart. A run that
    goes on with the count of the page before is judged together with the numbers of that page."""
    found = _numbered_page(document, page, numbered)
    runs = line_numbers.continued_runs(lambda earlier: _numbered_page(document, earlier, numbered).counts, page)
    text = _main_text(found) if runs else []
    if not text:
        return found.spans
    lines = _line_pitch(text)
    numbers = set()
    for run in runs:
        step = int(run[1].text) - int(run[0].text)
        pitch = statistics.median(below.y0 - above.y0 for above, below in itertools.pairwise(run))
        if lines is None or pitch <= step * LINE_PITCH * lines:
            numbers.update(run)
    return [span for span, word in zip(found.spans, found.words) if word not in numbers]


def _main_text(page: NumberedPage) -> list[Span]:
    """Return the spans of a page in the font size that holds most of its letters, without the spans of a number."""
    text = [span for span, word in zip(page.spans, page.words) if not line_numbers.NUMBER.fullmatch(word.text)]
    letters: dict[float, int] = {}
    for span in text:
        letters[span.size] = letters.get(span.size, 0) + len(span.text.strip())
    size = max(letters, key=letters.__getitem__, default=None)
    return [span for span in text if span.size == size]


def _numbered_page(document: pymupdf.Document, page: int, numbered: dict[int, NumberedPage]) -> NumberedPage:
    """Return the spans of a page with its line numbers, read once for the page itself and for the page after it."""
    if page not in numbered:
        spans = _spans(document[page])
        words = [line_numbers.Word(span.x0, span.y0, span.x1, span.y1, span.text.strip()) for span in spans]
        numbered[page] = NumberedPage(spans, words, line_numbers.line_counts(words))
    return numbered[page]


def _line_pitch(spans: list[Span]) -> float | None:
    """Return the distance from a text line to the next in the given spans of a page, or None without two lines.

    The lines of two columns may stand at different heights, so the pitch is the median distance from a span to the
    nearest span below it in its column, which is the nearest one that it overlaps from left to right."""
    spans = sorted(spans, key=lambda span: span.y0)
    steps = []
    for index, span in enumerate(spans):
        for below in itertools.islice(spans, index + 1, None):
            if below.y0 - span.y0 > SAME_LINE * span.size and below.x0 < span.x1 and below.x1 > span.x0:
                steps.append(below.y0 - span.y0)
                break
    return statistics.median(steps) if steps else None


def _free_strip(spans: list[Span], rect: pymupdf.Rect) -> tuple[int, int] | None:
    """Return the left and the right end of the widest strip near the middle of a page that the fewest spans cross,
    or None when text crosses every such strip, as on a page of one column."""
    low, high = int(rect.width * 0.35), int(rect.width * 0.65)
    cover = [0] * (high - low + 1)
    for span in spans:
        # A page number at the top or the bottom of the page may stand in the middle of the strip.
        at_edge = span.y1 < EDGE_SHARE * rect.height or span.y0 > (1 - EDGE_SHARE) * rect.height
        if not (at_edge and PAGE_NUMBER.fullmatch(span.text.strip())):
            for x in range(max(int(span.x0), low), min(int(span.x1), high) + 1):
                cover[x - low] += 1
    # A header or a wide float may cross the strip, therefore the strip is where the fewest spans lie.
    fewest = min(cover)
    if fewest > _may_cross(spans):
        return None
    best, start = (0, 0), None
    for x, count in enumerate(cover + [fewest + 1]):
        if count <= fewest and start is None:
            start = x
        elif count > fewest and start is not None:
            best, start = max(best, (x - start, start)), None
    length, begin = best
    return (low + begin, low + begin + length) if length >= MIN_GUTTER else None


def _may_cross(spans: list[Span]) -> int:
    """Return how many spans of a page may cross the gutter, as a header or a wide float does."""
    return 2 + len(spans) // 100


def _shows_columns(spans: list[Span], left: int, right: int) -> bool:
    """Tell whether at least MIN_COLUMN_LINES lines stand on each side of a strip, apart from the lines that cross it.

    The words of a line that TeX stretches are spans of their own, so a span counts with the others on its line."""
    across = [span for span in spans if int(span.x0) < right and int(span.x1) >= left]
    sides: tuple[list[Span], list[Span]] = ([], [])
    for span in spans:
        side = sides[int(span.x0) >= right]
        if (len(side) < MIN_COLUMN_LINES and (int(span.x1) < left or int(span.x0) >= right)
                and not any(_on_one_line(span, other) for other in [*across, *side])):
            side.append(span)
    return min(map(len, sides)) >= MIN_COLUMN_LINES


def _on_one_line(span: Span, other: Span) -> bool:
    return abs(_middle(span) - _middle(other)) <= SAME_LINE * max(span.size, other.size)


def _columns(spans: list[Span], split: float | None) -> list[list[Span]]:
    """Return the spans of each column.

    A span that reaches far into the two columns belongs to none, as a header or a wide float does. A line that
    sticks out of its column into the gutter stays in its column."""
    if split is None:
        return [list(spans)]
    columns: list[list[Span]] = [[], []]
    for span in spans:
        left, right = split - span.x0, span.x1 - split
        if min(left, right) <= WIDE_REACH:
            columns[right > left].append(span)
    return columns


def _line(row: list[Span], page: int, column: int) -> Line:
    row.sort(key=lambda span: span.x0)
    letters: dict[float, int] = {}
    for span in row:
        letters[round(span.size, 1)] = letters.get(round(span.size, 1), 0) + len(span.text)
    return Line(page, column, row[0].x0, min(span.y0 for span in row), max(span.x1 for span in row),
                max(span.y1 for span in row), max(letters, key=letters.__getitem__), _spaced(row))


def _spaced(row: list[Span]) -> str:
    """Return the text of a line with one space at each word gap.

    MuPDF reads a space only into a gap of about 0.15 of the font size, therefore the words of a tight line run
    together. TeX gives every word gap of a line one width, and more after a period or a comma. A line in one font
    size is tight when it shows several narrow gaps of one width and nearly no wider gap between two words."""
    glyphs = [(char, x0, x1, span.size) for span in row for char, x0, x1 in span.glyphs]
    if any(ACCENT.search(span.text) for span in row):
        glyphs = _accented(glyphs)
    ink = [index for index, glyph in enumerate(glyphs) if not glyph[0].isspace()]
    pairs = [(glyphs[left], glyphs[right], right - left > 1) for left, right in itertools.pairwise(ink)]
    gaps = [(right[1] - left[2]) / left[3] for left, right, _space in pairs]
    narrow = [TIGHT_GAP <= gap <= WORD_GAP and (left[0].isalnum() or left[0] in CLOSING)
              and (right[0].isalnum() or right[0] in OPENING) for gap, (left, right, _space) in zip(gaps, pairs)]
    # Letters that stand apart one by one, as in a link that TeX stretches, show narrow gaps in a row.
    place = 0
    for value, run in itertools.groupby(narrow):
        length = len(list(run))
        if value and length >= SPACED_RUN:
            narrow[place:place + length] = [False] * length
        place += length
    tight = [gap for gap, flag in zip(gaps, narrow) if flag]
    wide = sum(1 for gap, (left, _right, space) in zip(gaps, pairs) if left[0].isalnum() and (space or gap > WORD_GAP))
    sizes = [glyphs[index][3] for index in ink]
    limit = WORD_GAP
    if (len(tight) >= max(TIGHT_GAPS, TIGHT_TO_WIDE * wide) and len(tight) <= TIGHT_SHARE * len(pairs)
            and max(sizes) - min(sizes) < SIZE_TOLERANCE):
        typical = statistics.median(tight)
        if sum(abs(gap - typical) <= GAP_TOLERANCE for gap in tight) >= ONE_WIDTH * len(tight):
            limit = typical - GAP_TOLERANCE
    text = glyphs[ink[0]][0] if ink else ""
    for gap, flag, (_left, right, space) in zip(gaps, narrow, pairs):
        if space or gap > WORD_GAP or (flag and gap >= limit):
            text += " "
        text += right[0]
    return text


def _accented(glyphs: list[tuple[str, float, float, float]]) -> list[tuple[str, float, float, float]]:
    """Return the glyphs of a line with each accent that TeX draws as a glyph of its own set on its letter.

    TeX centers such an accent over or under its letter, so the middle of the accent lies inside the box of the
    letter, while a mark between two letters lies inside the box of none."""
    marks: dict[int, str] = {}
    drawn = set()
    for index, (char, x0, x1, _size) in enumerate(glyphs):
        if char in COMBINING:
            letter = next((place for place, (other, left, right, _size) in enumerate(glyphs)
                           if left < (x0 + x1) / 2 < right and other.isalpha() and other not in COMBINING), None)
            if letter is not None:
                marks[letter] = marks.get(letter, "") + COMBINING[char]
                drawn.add(index)
    # MuPDF reads a space into the step from an accent below a capital back to the right edge of the capital.
    drawn.update(index for index, (char, x0, x1, _size) in enumerate(glyphs) if char.isspace() and any(
        glyphs[letter][1] < (x0 + x1) / 2 < glyphs[letter][2] for letter in marks))
    return [(unicodedata.normalize("NFC", DOTLESS.get(char, char) + marks[index]) if index in marks else char,
             x0, x1, size) for index, (char, x0, x1, size) in enumerate(glyphs) if index not in drawn]


def _is_heading(text: str) -> bool:
    return HEADING.fullmatch(text.replace(" ", "")) is not None


def _repeated_edge_lines(pages: dict[int, list[Line]], height: float, heading: tuple[int, int]) -> set[Line]:
    """Return the page numbers and the lines that repeat at the top or the bottom of the pages, as headers do.

    Such a line stands apart from the text, while the first and the last line of a column lie close to the next.
    Once two pages show a line apart, the line counts on every page, also below a column that reaches down to it.
    One of the two stands before the heading of the list, by its page and its place in the page, since the lines of
    a list with wide line spacing stand apart too and may read the same on two pages. LaTeX sets the header of every
    page as one line at one height, so each line that stands apart at the height of a header is a part of a header."""
    seen: dict[tuple[str, int], set[int]] = {}
    early: set[tuple[str, int]] = set()
    edge: list[tuple[tuple[str, int], Line, bool]] = []
    found = set()
    for number, lines in pages.items():
        for index, line in enumerate(lines):
            top, bottom = line.y1 < EDGE_SHARE * height, line.y0 > (1 - EDGE_SHARE) * height
            if top or bottom:
                key = (DIGITS.sub("0", line.text), round(line.y0 / 3))
                apart = _apart(line, lines, top)
                edge.append((key, line, apart))
                if apart:
                    if PAGE_NUMBER.fullmatch(line.text):
                        found.add(line)
                    seen.setdefault(key, set()).add(line.page)
                    if (number, index) < heading:
                        early.add(key)
    headers = {key for key in early if len(seen[key]) > 1}
    heights = {place for _text, place in headers}
    return found | {line for key, line, apart in edge if key in headers or (apart and key[1] in heights)}


def _apart(line: Line, lines: list[Line], top: bool) -> bool:
    """Tell whether no line of the page lies within EDGE_GAP points on the text side of a line."""
    for other in lines:
        if other is not line and other.x0 < line.x1 and other.x1 > line.x0:
            gap = other.y0 - line.y1 if top else line.y0 - other.y1
            if -line.size < gap < EDGE_GAP:
                return False
    return True


def _until_end_heading(lines: list[Line], size: float) -> list[Line]:
    """Cut the lines at the heading of an appendix or of another part that follows the list."""
    foreign = [abs(line.size - size) > SIZE_TOLERANCE for line in lines]
    for index, line in enumerate(lines):
        named = END_HEADING.fullmatch(line.text) is not None
        if named and foreign[index]:
            return lines[:index]
        # Only their words tell these two headings from a line of an entry or of a float, after which the list goes on.
        short = named and len(line.text) < 40
        section = foreign[index] and line.size > size and APPENDIX_SECTION.fullmatch(line.text)
        if (short or section) and not _numbers_go_on(lines, foreign, index):
            return lines[:index]
    return lines


def _numbers_go_on(lines: list[Line], foreign: list[bool], index: int) -> bool:
    """Tell whether numbered entries stand before and after a line, which therefore cannot end the list.

    The numbers of a list count up one by one, and no text after the list opens a line with the number that follows."""
    starts = _numbered_starts(lines, foreign)
    return bool(starts) and min(starts) < index < max(starts)


def _entries(lines: list[Line], document: pymupdf.Document) -> list[Entry]:
    """Split the lines of the list into its entries by their labels, or by the hanging first lines without labels."""
    if not lines:
        return []
    size = lines[0].size
    lines = _until_end_heading(lines, size)
    # A footnote, a float, or the text after the list stands in another font size than the list.
    foreign = [abs(line.size - size) > SIZE_TOLERANCE for line in lines]
    starts = _labeled_starts(lines, foreign)
    if starts:
        _mark_off_margin(lines, foreign, starts)
    else:
        _mark_footnotes(lines, foreign, document)
        starts = _hanging_starts(lines, foreign)
    _mark_blocks_below(lines, foreign, starts)
    return _split(lines, foreign, starts)


def _labeled_starts(lines: list[Line], foreign: list[bool]) -> dict[int, str]:
    """Return the first line of each entry without its label, by the index of the line, or {} without labels."""
    starts = _numbered_starts(lines, foreign)
    if starts:
        return starts
    starts = {index: line.text[match.end():] for index, line in enumerate(lines)
              if not foreign[index] and (match := KEY_LABEL.match(line.text))}
    return starts if len(starts) >= MIN_LABELS else {}


def _hanging_starts(lines: list[Line], foreign: list[bool]) -> dict[int, str]:
    """Return the first line of each entry of a list without labels, by the index of the line.

    An entry starts at the left edge of its column, and its further lines stand to the right of that edge. A column
    whose lines all start at one place shows no edge. Its lines go on with the entry of the column before it when
    the last line there is not the last line of its entry."""
    columns: dict[tuple[int, int], list[int]] = {}
    for index, line in enumerate(lines):
        if not foreign[index]:
            columns.setdefault((line.page, line.column), []).append(index)
    starts: dict[int, str] = {}
    before: list[int] = []
    for members in columns.values():
        edge = min(lines[index].x0 for index in members)
        hanging = [index for index in members if lines[index].x0 - edge < HANG]
        if len(hanging) < len(members) or not before or not _goes_on(lines, before):
            starts.update({index: lines[index].text for index in hanging})
        before = members
    return starts


def _goes_on(lines: list[Line], column: list[int]) -> bool:
    """Tell whether the entry of the last line of a column goes on in the next column.

    TeX fills every line of a justified entry but the last, so the entry goes on after a line that reaches the right
    edge of its column."""
    return max(lines[index].x1 for index in column) - lines[column[-1]].x1 < HANG


def _mark_off_margin(lines: list[Line], foreign: list[bool], starts: dict[int, str]) -> None:
    """Mark the lines of a labeled list that are no lines of an entry as foreign, such as a caption, a table, a
    footnote, or a biography in the font size of the list.

    LaTeX puts a float above and a footnote below the text of a column, so only a line above the first or below the
    last label of a column may be foreign. Such a line is foreign when it starts where no line of an entry starts, and
    in a column without labels when the entry above it has ended. A line that opens with a label stays, since the
    count of the entries may have missed it."""
    lengths = {index: len(lines[index].text) - len(text) for index, text in starts.items()}
    spans = _label_spans(lines, starts)
    offsets = _label_offsets(lines, foreign, lengths, spans)
    width = _full_width(lines, foreign, starts, spans)
    ended, link = False, ""
    for index, line in enumerate(lines):
        key = (line.page, line.column)
        first, last = spans.get(key, (index, index))
        if index not in starts and not first < index < last and not _opens_with_label(line):
            entry = last if index > last else first
            off = _starts_off_margin(line, lines[entry], offsets.get(lengths[entry], ())) if key in spans else ended
            foreign[index] = foreign[index] or off
        if not foreign[index] and width is not None and index + 1 < len(lines):
            # The text of a line with a label starts at the first of the places to the right of the label.
            reach = line.x1 - line.x0 - min(offsets.get(lengths.get(index), ()), default=0)
            # TeX cannot stretch a line that holds one part of a link, which goes on in the next line.
            link = (link if _continues(link, line.text, False) else "") + line.text
            ended = reach < width - HANG and not _continues(link, lines[index + 1].text, False)


def _label_spans(lines: list[Line], starts: dict[int, str]) -> dict[tuple[int, int], tuple[int, int]]:
    """Return the first and the last line with a label of each column, by page and column."""
    spans: dict[tuple[int, int], tuple[int, int]] = {}
    for index in starts:
        key = (lines[index].page, lines[index].column)
        spans[key] = (spans.get(key, (index, index))[0], index)
    return spans


def _label_offsets(lines: list[Line], foreign: list[bool], lengths: dict[int, int],
                   spans: dict[tuple[int, int], tuple[int, int]]) -> dict[int, set[int]]:
    """Return how far to the right of its label the further lines of an entry start, by the length of the label.

    LaTeX sets an entry as a paragraph with one left margin, out of which its label hangs by a fixed width, and a
    class may indent the further lines of each block of an entry. The lines between two labels of a column show these
    places."""
    found: dict[int, set[int]] = {}
    for first, last in spans.values():
        for index in range(first, last):
            if index in lengths:
                entry = index
            elif not foreign[index]:
                found.setdefault(lengths[entry], set()).add(round(lines[index].x0 - lines[entry].x0))
    return found


def _starts_off_margin(line: Line, label: Line, offsets: Collection[int]) -> bool:
    """Tell whether a line starts at none of the places at which the further lines of an entry with this label start."""
    return bool(offsets) and all(abs(line.x0 - label.x0 - offset) > OFF_MARGIN * line.size for offset in offsets)


def _full_width(lines: list[Line], foreign: list[bool], starts: dict[int, str],
                spans: dict[tuple[int, int], tuple[int, int]]) -> float | None:
    """Return the width of a full line of an entry from the margin of the entry, or None for a list that is not
    justified.

    TeX fills every line of a justified paragraph but the last. The lines between two labels of a column that go on
    below therefore end one width to the right of where the next line starts."""
    widths = [lines[index].x1 - lines[index + 1].x0 for first, last in spans.values() for index in range(first, last)
              if not foreign[index] and not foreign[index + 1] and index + 1 not in starts]
    if not widths:
        return None
    width = statistics.median(widths)
    short = sum(other < width - HANG for other in widths)
    return width if FORCED_BREAKS * short <= len(widths) else None


def _mark_footnotes(lines: list[Line], foreign: list[bool], document: pymupdf.Document) -> None:
    """Mark the lines below the footnote rule of a column as foreign, in the font size of the list or not.

    LaTeX draws a short rule from the left edge of a column above its footnotes and sets only notes below it. A rule
    for repeated authors lies on the first line of its entry, and the rule of a table spans the table."""
    columns: dict[tuple[int, int], list[int]] = {}
    for index, line in enumerate(lines):
        if not foreign[index]:
            columns.setdefault((line.page, line.column), []).append(index)
    rules: dict[int, list[tuple[float, float, float]]] = {}
    for (page, _column), indexes in columns.items():
        if page not in rules:
            rules[page] = _flat_rules(document[page])
        left = min(lines[index].x0 for index in indexes)
        width = max(lines[index].x1 for index in indexes) - left
        for x0, x1, y in rules[page]:
            crossed = any(lines[index].y0 < y < lines[index].y1 for index in indexes)
            if abs(x0 - left) <= HANG and x1 - x0 <= RULE_SHARE * width and not crossed:
                for index in indexes:
                    foreign[index] = foreign[index] or lines[index].y0 > y


def _flat_rules(page: pymupdf.Page) -> list[tuple[float, float, float]]:
    """Return the horizontal rules of a page, each as its left end, its right end, and its place from the top."""
    try:
        drawings = page.get_cdrawings()
    except READ_ERRORS:
        return []
    rules = []
    for drawing in drawings:
        x0, y0, x1, y1 = drawing["rect"]
        if y1 - y0 <= RULE_HEIGHT and x1 - x0 > HANG:
            rules.append((x0, x1, (y0 + y1) / 2))
    return rules


def _mark_blocks_below(lines: list[Line], foreign: list[bool], starts: dict[int, str]) -> None:
    """Mark a footnote or a float below the list lines of a column as foreign, in the same font size or not.

    Inside an entry, each line follows the line above it at the pitch of the list. After a wider gap, a column goes
    on with a new entry or with a block that is no part of the list."""
    pitches = [below.y0 - above.y0 for above, below in itertools.pairwise(lines)
               if (above.page, above.column) == (below.page, below.column) and below.y0 > above.y0]
    if not pitches:
        return
    pitch = statistics.median(pitches)
    inside = False
    for index in range(1, len(lines)):
        above, line = lines[index - 1], lines[index]
        if (above.page, above.column) != (line.page, line.column):
            inside = False
        elif (line.y0 - above.y0 > BLOCK_GAP * pitch and not foreign[index - 1] and index not in starts
              and not _opens_with_label(line)):
            inside = True
        if inside:
            foreign[index] = True
            starts.pop(index, None)


def _opens_with_label(line: Line) -> bool:
    return any(label.match(line.text) for label in (BRACKET_LABEL, DOTTED_LABEL, KEY_LABEL))


def _numbered_starts(lines: list[Line], foreign: list[bool]) -> dict[int, str]:
    """Return the first line of each numbered entry without its label, by the index of the line, or {} for a list
    without numbers."""
    # A line of an entry without labels may open with a number and a period, such as an edition.
    for label, fewest in ((BRACKET_LABEL, 1), (DOTTED_LABEL, MIN_LABELS)):
        starts: dict[int, str] = {}
        expected = above = None
        for index, line in enumerate(lines):
            match = None if foreign[index] else label.match(line.text)
            number = int(match.group(1)) if match else 0
            # A label that the text extraction lost leaves a gap of one or two numbers.
            if (match and (number <= 2 if expected is None else 0 <= number - expected <= 2)
                    and not _right_of_label(line, above)):
                starts[index] = line.text[match.end():]
                expected, above = number + 1, line
        if len(starts) >= fewest:
            return starts
    return {}


def _right_of_label(line: Line, label: Line | None) -> bool:
    """Tell whether a line starts to the right of the label above it in its column, as a line inside an entry does.

    LaTeX sets the labels of a list against one margin, and a label with more digits reaches further to the left."""
    return label is not None and (label.page, label.column) == (line.page, line.column) and line.x0 - label.x0 > HANG


def _split(lines: list[Line], foreign: list[bool], starts: dict[int, str]) -> list[Entry]:
    """Return the entries that open at the given lines, each with the lines up to the next entry.

    Foreign lines split an entry, such as a footnote below the column in which the entry starts. The lines after
    them belong to the entry when the next entry follows, and after the last entry only when they are few. The next
    entry shows where an entry ends, so only the last entry is cut at MAX_ENTRY_LINES."""
    entries: list[list[str]] = []
    pending: list[str] = []
    interrupted = False
    for index, line in enumerate(lines):
        if index in starts:
            if entries:
                entries[-1] += pending
            entries.append([starts[index]])
            pending, interrupted = [], False
        elif foreign[index]:
            interrupted = bool(entries)
        elif entries:
            (pending if interrupted else entries[-1]).append(line.text)
    if entries and len(pending) <= TAIL_LINES:
        entries[-1] += pending
    texts = [_joined(entry) for entry in entries[:-1]] + [_joined(entry[:MAX_ENTRY_LINES]) for entry in entries[-1:]]
    return [Entry(number, text) for number, text in enumerate((text for text in texts if text), start=1)]


def _joined(lines: list[str]) -> str:
    """Join the lines of an entry with a space, and with none where a link, a DOI, or an arXiv ID goes on."""
    text = ""
    for index, line in enumerate(lines):
        if line:
            text += ("" if _continues(text, line, index == len(lines) - 1) else " ") + line
    return CHAPTER_DOI_GAP.sub(r"\1_", " ".join(text.split()))


def _continues(text: str, line: str, last: bool) -> bool:
    """Tell whether a line goes on with the link, the DOI, or the arXiv ID at which the text before it ends."""
    tail = LINK_TAIL.search(text)
    if not tail or line[0] in OPENING or LINK_HEAD.match(line) or YEAR_LINE.fullmatch(line):
        return False
    link, head = tail.group(), line.split()[0]
    # No style prints a colon after a link, so a first word with a colon before further words is a label, as Accessed:.
    if head[-1] == ":" and head != line:
        return False
    if link.lower().startswith("arxiv:"):
        arxiv, digits = ARXIV_TAIL.fullmatch(link), DIGITS.match(head)
        return bool(arxiv and digits) and len(arxiv.group(1)) + len(digits.group()) <= 5
    if link[-1] in LINK_BREAKS or head[0] in LINK_BREAKS + ".":
        return True
    # A link may break inside a word, and its last part may stand alone on the last line of the entry.
    alone = last and head == line
    if link[-1] in ".:":
        return head[0].isdigit() or (head[0].islower() and (alone or any(mark in head for mark in "./")))
    return link[-1].isalnum() and (alone or any(mark in head for mark in LINK_BREAKS))

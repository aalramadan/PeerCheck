"""Content that runs into the margins of the template, page by page: words, images, and drawings whose visible ink lies
beyond the text block of the profile, apart from the running heads, page numbers, and line numbers of the template
and the stamp of a preprint server."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from peercheck.findings import Finding, Severity, excerpt
from peercheck.models import Paper
from peercheck.profile import FormatRules, Profile

CHECK = "margins"
# A line of the acmart sample paper and a table of a Word paper reach 9 pt past the profile margins, other clean papers
# 5.5 pt. HotCRP flags a text block 9 pt larger than the template.
DEFAULT_TOLERANCE = 12.0
SIDES = ("top", "right", "bottom", "left")
DIRECTIONS = {"top": (0, -1), "right": (1, 0), "bottom": (0, 1), "left": (-1, 0)}
KINDS = ("text", "image", "drawing")
READ_ERRORS = (OSError, RuntimeError, ValueError, pymupdf.mupdf.FzErrorBase)
# Glyph boxes, since the font box of a large letter, such as one in a figure, reaches far beyond its ink.
WORD_FLAGS = pymupdf.TEXTFLAGS_WORDS | pymupdf.TEXT_ACCURATE_BBOXES
# Lines of text and rows of a table stand about 2 pt apart, and the running heads of acmart 14 pt from the text block.
HEAD_GAP = 4.0
SAME_HEIGHT = 0.5
RULE_HEIGHT = 1.5
LINE_NUMBER = re.compile(r"[0-9]+")
MIN_LINE_NUMBERS = 3
ALIGNMENT = 1.0
PREPRINT_ID = re.compile(r"arXiv:\S+")
# The letters of a font that names no descender height reach below their text box, by less than this part of its height.
LETTER_REACH = 0.3
INK_ZOOM = 2
# Gray levels from this value up count as blank paper, such as the near-white background of a photo.
PAPER_GRAY = 245
INK = bytes(0 if level < PAPER_GRAY else 1 for level in range(256))


@dataclass(eq=False)
class Mark:
    """A word, an image, or a drawing of a page, with its box on the page before any turn for display."""

    kind: str
    rect: pymupdf.Rect
    text: str = ""

    def span(self, block: pymupdf.Rect, side: str) -> tuple[float, float]:
        """Return how far the near and the far edge of the box lie beyond one side of the text block."""
        box = self.rect
        return {"top": (block.y0 - box.y1, block.y0 - box.y0), "right": (box.x0 - block.x1, box.x1 - block.x1),
                "bottom": (box.y0 - block.y1, box.y1 - block.y1), "left": (block.x0 - box.x1, block.x0 - box.x0)}[side]

    def overshoot(self, block: pymupdf.Rect) -> float:
        """Return how far the box reaches past the text block on its farthest side, negative if it stays inside."""
        return max(self.span(block, side)[1] for side in SIDES)

    def above_or_below(self, block: pymupdf.Rect) -> bool:
        """Return True if the box lies wholly above or wholly below the text block."""
        return self.span(block, "top")[0] >= 0 or self.span(block, "bottom")[0] >= 0


@dataclass
class PageMarks:
    """The marks of one page that reach past its text block, with those that the template puts in the margins."""

    number: int
    block: pymupdf.Rect
    marks: list[Mark]
    template: set[Mark]


@dataclass(frozen=True)
class PageInk:
    """A gray render of a page with INK_ZOOM pixels to a point, where 0 marks ink and 1 blank paper."""

    pixels: bytes
    width: int
    height: int
    stride: int

    def reach(self, block: pymupdf.Rect, box: pymupdf.Rect, side: str) -> float | None:
        """Return how far the ink in the part of the box beyond one side of the text block reaches past that side."""
        z = INK_ZOOM
        c0, r0, c1, r1 = _pixels(box)
        if side == "right":
            c0 = math.floor(block.x1 * z)
        elif side == "left":
            c1 = math.ceil(block.x0 * z)
        elif side == "bottom":
            r0 = math.floor(block.y1 * z)
        else:
            r1 = math.ceil(block.y0 * z)
        c0, r0, c1, r1 = max(c0, 0), max(r0, 0), min(c1, self.width), min(r1, self.height)
        if c0 >= c1 or r0 >= r1:
            return None
        lines = {row: self.pixels[row * self.stride + c0: row * self.stride + c1] for row in range(r0, r1)}
        inked = [row for row, line in lines.items() if 0 in line]
        if not inked:
            return None
        if side == "top":
            return block.y0 - min(inked) / z
        if side == "bottom":
            return (max(inked) + 1) / z - block.y1
        if side == "left":
            return block.x0 - (c0 + min(lines[row].find(0) for row in inked)) / z
        return (c0 + max(lines[row].rfind(0) for row in inked) + 1) / z - block.x1


def check(paper: Paper, profile: Profile, workdir: Path) -> list[Finding]:
    """Return an error for each page whose content runs past a margin of the template by more than the tolerance."""
    rules = profile.format
    if rules.margins is None:
        return []
    tolerance = float(profile.options("margins").get("tolerance", DEFAULT_TOLERANCE))
    try:
        document = pymupdf.open(paper.pdf)
    except READ_ERRORS:
        return [_error("the margin check could not open the PDF")]
    findings = []
    with document:
        if document.needs_pass:
            return [_error("the margin check could not open the PDF, which needs a password")]
        pages = []
        for page in document:
            try:
                marks = _page_marks(page, rules, tolerance)
            except READ_ERRORS as exc:
                findings.append(_error(f"the margin check could not read this page ({exc})", page.number + 1))
                continue
            if marks is not None:
                pages.append(marks)
        _add_recurring_heads(pages, tolerance)
        for marks in pages:
            try:
                finding = _page_finding(document[marks.number], marks, tolerance)
            except READ_ERRORS as exc:
                finding = _error(f"the margin check could not render this page ({exc})", marks.number + 1)
            if finding is not None:
                findings.append(finding)
    return sorted(findings, key=lambda finding: finding.page or 0)


def _page_marks(page: pymupdf.Page, rules: FormatRules, tolerance: float) -> PageMarks | None:
    """Return the marks of a page beyond its text block, or None if the page has another size than the profile."""
    frame = page.rect * page.derotation_matrix
    height, width = rules.paper_size
    if max(abs(frame.width - width), abs(frame.height - height)) > rules.paper_size_tolerance:
        return None
    top, right, bottom, left = rules.margins
    block = pymupdf.Rect(frame.x0 + left, frame.y0 + top, frame.x1 - right, frame.y1 - bottom)
    marks = [mark for mark in _marks(page, frame) if mark.overshoot(block) > 0]
    template = _line_numbers(marks, block) | _preprint_stamp(marks, block)
    template |= _running_heads([mark for mark in marks if mark not in template], block, tolerance)
    return PageMarks(page.number, block, marks, template)


def _marks(page: pymupdf.Page, frame: pymupdf.Rect) -> list[Mark]:
    """Return the words, images, and drawings of the page, each cut to the page."""
    boxes = [("text", tuple(word[:4]), word[4]) for word in page.get_text("words", flags=WORD_FLAGS)]
    boxes += [("image", tuple(info["bbox"]), "") for info in page.get_image_info()]
    # get_cdrawings gives the paths of get_drawings as plain tuples, in about two thirds of the time.
    for path in page.get_cdrawings():
        # A stroke reaches half its width beyond the points of its path.
        half = (path.get("width") or 0.0) / 2 if "s" in path["type"] else 0.0
        x0, y0, x1, y1 = path["rect"]
        boxes.append(("drawing", (x0 - half, y0 - half, x1 + half, y1 + half), ""))
    marks = []
    for kind, (x0, y0, x1, y1), text in boxes:
        box = pymupdf.Rect(max(x0, frame.x0), max(y0, frame.y0), min(x1, frame.x1), min(y1, frame.y1))
        if box.x0 <= box.x1 and box.y0 <= box.y1:
            marks.append(Mark(kind, box, text))
    return marks


def _line_numbers(marks: list[Mark], block: pymupdf.Rect) -> set[Mark]:
    """Return the line numbers in the side margins, as the review option of acmart and the listings package print them.

    Line numbers stand in a column of aligned numbers that count up by a fixed step from one line to the next. A listing
    starts its count again.
    """
    found = set()
    for side in ("left", "right"):
        numbers = [mark for mark in marks if mark.kind == "text" and LINE_NUMBER.fullmatch(mark.text)
                   and mark.span(block, side)[0] >= 0]
        for edge in ("x0", "x1"):
            for column in _columns(numbers, edge):
                counted = [mark for run in _runs(column) if len(run) > 1 for mark in run]
                if len(counted) >= MIN_LINE_NUMBERS:
                    found.update(counted)
    return found


def _columns(words: list[Mark], edge: str) -> list[list[Mark]]:
    """Group the words whose left or right edges line up, each group from top to bottom."""
    columns: list[list[Mark]] = []
    for word in sorted(words, key=lambda mark: getattr(mark.rect, edge)):
        if columns and getattr(word.rect, edge) - getattr(columns[-1][0].rect, edge) <= ALIGNMENT:
            columns[-1].append(word)
        else:
            columns.append([word])
    return [sorted(column, key=lambda mark: mark.rect.y0) for column in columns]


def _runs(column: list[Mark]) -> list[list[Mark]]:
    """Split a column of numbers, from top to bottom, into runs that count up by a fixed step."""
    runs: list[list[Mark]] = []
    for mark in column:
        run = runs[-1] if runs else []
        step = int(run[1].text) - int(run[0].text) if len(run) > 1 else None
        rise = int(mark.text) - int(run[-1].text) if run else 0
        if rise > 0 and step in (None, rise):
            run.append(mark)
        else:
            runs.append([mark])
    return runs


def _preprint_stamp(marks: list[Mark], block: pymupdf.Rect) -> set[Mark]:
    """Return the words of the stamp that arXiv prints up the left margin, which is no content of the paper.

    The stamp reads from the bottom up, therefore the tops of its letters share the left edge of its identifier.
    """
    beside = [mark for mark in marks if mark.kind == "text" and mark.span(block, "left")[0] >= 0]
    found = set()
    for mark in beside:
        if PREPRINT_ID.fullmatch(mark.text) and mark.rect.height > mark.rect.width:
            found.update(word for word in beside if abs(word.rect.x0 - mark.rect.x0) <= ALIGNMENT)
    return found


def _running_heads(marks: list[Mark], block: pymupdf.Rect, tolerance: float) -> set[Mark]:
    """Return the text and the rules above or below the text block that stand apart from it, such as running heads.

    Content that crosses the edge of the text block, and each box within HEAD_GAP of such content, belongs to the text
    block. A box beyond a wider gap stands apart.
    """
    found = set()
    for side in ("top", "bottom"):
        spans = [(mark, *mark.span(block, side)) for mark in marks]
        reach = max((far for _, near, far in spans if near < 0 < far), default=0.0)
        apart = False
        for mark, near, far in sorted((span for span in spans if span[1] >= 0), key=lambda span: span[1]):
            apart = apart or near >= reach + HEAD_GAP
            if not apart:
                reach = max(reach, far)
            elif _template_part(mark, block, tolerance):
                found.add(mark)
    return found


def _add_recurring_heads(pages: list[PageMarks], tolerance: float) -> None:
    """Add the running heads that content of a page reaches but that stand apart at the same height on another page."""
    heads = [(page.number, mark.rect) for page in pages for mark in page.template if mark.above_or_below(page.block)]
    for page in pages:
        for mark in page.marks:
            if mark not in page.template and mark.above_or_below(page.block) and \
                    _template_part(mark, page.block, tolerance) and \
                    any(number != page.number and abs(mark.rect.y0 - head.y0) <= SAME_HEIGHT and
                        abs(mark.rect.y1 - head.y1) <= SAME_HEIGHT for number, head in heads):
                page.template.add(mark)


def _template_part(mark: Mark, block: pymupdf.Rect, tolerance: float) -> bool:
    """Return True for text or a rule that stays over the width of the text block, as running heads do."""
    shape = mark.kind == "text" or (mark.kind == "drawing" and mark.rect.height <= RULE_HEIGHT)
    return shape and mark.rect.x0 >= block.x0 - tolerance and mark.rect.x1 <= block.x1 + tolerance


def _page_finding(page: pymupdf.Page, marks: PageMarks, tolerance: float) -> Finding | None:
    """Return the finding of one page, or None if the ink of its content stays within the tolerance."""
    block = marks.block
    candidates = [mark for mark in marks.marks if mark not in marks.template and mark.overshoot(block) > tolerance]
    if not candidates:
        return None
    ink = _render(page, marks.template)
    reached: dict[str, tuple[float, list[Mark]]] = {}
    for mark in candidates:
        for side in SIDES:
            if mark.span(block, side)[1] <= tolerance:
                continue
            distance = ink.reach(block, mark.rect, side)
            if distance is not None and distance > tolerance:
                farthest, marks_of_side = reached.get(side, (0.0, []))
                reached[side] = (max(farthest, distance), marks_of_side + [mark])
    return _finding(page, reached, tolerance) if reached else None


def _render(page: pymupdf.Page, blanked: set[Mark]) -> PageInk:
    """Render the page in gray before any turn for display, without annotations and with the given boxes left blank."""
    turn = page.derotation_matrix
    matrix = pymupdf.Matrix(turn.a, turn.b, turn.c, turn.d, 0, 0) * pymupdf.Matrix(INK_ZOOM, INK_ZOOM)
    pix = page.get_pixmap(matrix=matrix, colorspace=pymupdf.csGRAY, alpha=False, annots=False)
    pix.set_origin(0, 0)
    for mark in blanked:
        reach = LETTER_REACH * min(mark.rect.width, mark.rect.height) if mark.kind == "text" else 0.0
        pix.set_rect(pymupdf.IRect(_pixels(mark.rect + (0, 0, 0, reach))), (255,))
    return PageInk(pix.samples.translate(INK), pix.width, pix.height, pix.stride)


def _pixels(box: pymupdf.Rect) -> tuple[int, int, int, int]:
    """Return the pixels of a render that cover the box and one more on each side, where a thin line leaves its edge."""
    z = INK_ZOOM
    return math.floor(box.x0 * z) - 1, math.floor(box.y0 * z) - 1, math.ceil(box.x1 * z) + 1, math.ceil(box.y1 * z) + 1


def _finding(page: pymupdf.Page, reached: dict[str, tuple[float, list[Mark]]], tolerance: float) -> Finding:
    """Return one error that names each side the content of the page runs into and how far."""
    parts = [f"{round(reached[side][0] * INK_ZOOM) / INK_ZOOM:g} pt into the {_shown(side, page)} margin"
             for side in SIDES if side in reached]
    marks = {mark for _, marks_of_side in reached.values() for mark in marks_of_side}
    kinds = ", ".join(kind for kind in KINDS if any(mark.kind == kind for mark in marks))
    message = f"content ({kinds}) runs {' and '.join(parts)}, beyond the tolerance of {tolerance:g} pt"
    words = " ".join(mark.text for mark in sorted(marks, key=lambda mark: (mark.rect.y0, mark.rect.x0)) if mark.text)
    return Finding(f"{CHECK}.overflow", Severity.ERROR, message, page.number + 1, excerpt(words))


def _shown(side: str, page: pymupdf.Page) -> str:
    """Return the name of a side of the page as a viewer shows the page, which may turn it."""
    x, y = DIRECTIONS[side]
    turn = page.rotation_matrix
    shown = (round(x * turn.a + y * turn.c), round(x * turn.b + y * turn.d))
    return next(name for name, direction in DIRECTIONS.items() if direction == shown)



def _error(message: str, page: int | None = None) -> Finding:
    return Finding(f"{CHECK}.error", Severity.WARNING, message, page)

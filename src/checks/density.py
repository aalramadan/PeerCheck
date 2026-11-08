"""Papers far denser than the rest of their batch: the characters per text page that banal counts and the proportion
of characters below 8 pt, each compared with the other papers and, where the profile gives one, with the template."""

from __future__ import annotations

import math
import re
import statistics
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from peercheck.checks.layout import Layout
from peercheck.findings import Finding, Severity
from peercheck.models import Paper
from peercheck.profile import Profile, ProfileError

CHECK = "density"
# Page 1 holds the title block and the abstract, which other sizes than the body set.
FIRST_TEXT_PAGE = 2
# With fewer text pages, the denser half is one page, which a full-page table in small type fills on its own.
MIN_TEXT_PAGES = 3
# TeX sets 8 pt type at 7.97 PDF points, which microtype narrows to 7.89, and 7 pt type at 6.90 to 7.04.
SMALL_TYPE = 7.75
# Fewer characters leave the proportion to one table or one figure.
MIN_CHARACTERS = 5000
DEFAULT_PERCENTILE = 95
# The 95th percentile of 29 other papers lies between their second and third largest values, therefore no single paper
# sets it.
DEFAULT_MIN_BATCH = 30
# How far a paper must lie above the larger of the percentile and the template. In batches of 30 drawn from arXiv cs.SE
# papers of one template, a margin of 6% warned on fewer than 0.1% of the papers without a template measure and on
# none with one, while a quarter of the characters below 8 pt stood above every paper but the two densest in small type.
CHARACTER_MARGIN = 0.06
SMALL_TYPE_FACTOR = 1.5
MIN_SMALL_TYPE = 0.25
# Text within this many points of the body size counts as body text for the place of the line numbers.
BODY_RANGE = 0.5
LINE_NUMBER = re.compile(r"\d+")
READ_ERRORS = (OSError, RuntimeError, ValueError, pymupdf.mupdf.FzErrorBase)


@dataclass(frozen=True)
class Density:
    """The density measures of one paper and the pages that show each measure best."""

    text_pages: int
    characters: float | None
    densest_page: int | None
    small: int
    total: int
    small_type_page: int | None

    @property
    def small_type(self) -> float | None:
        """Return the proportion of the characters of the main text below 8 pt, or None with too few characters."""
        return self.small / self.total if self.total >= MIN_CHARACTERS else None


def measure(paper: Paper, layout: Layout | None) -> Density | None:
    """Return the density measures of a paper from its banal layout and its PDF, or None if banal could not read it.

    The main text holds the pages before the page where the references start, without blank pages. Its text pages
    are those after page 1 that banal types as body, which leaves out pages of figures.
    """
    if layout is None:
        return None
    end = layout.references_start or layout.total_pages + 1
    kinds = list(enumerate(layout.page_types[: end - 1], start=1))
    text = {number: count for (number, kind), count in zip(kinds, layout.page_characters)
            if number >= FIRST_TEXT_PAGE and kind == "body"}
    small, total, small_type_page = _small_type(paper.pdf, [number for number, kind in kinds if kind != "blank"])
    densest = max(text, key=lambda number: text[number]) if text else None
    return Density(len(text), _denser_half(list(text.values())), densest, small, total, small_type_page)


def check_batch(measures: dict[int, Density | None], profile: Profile) -> dict[int, list[Finding]]:
    """Return a warning for each paper whose density lies far above the other papers, by paper ID.

    Options of `density` in the profile: percentile (default 95) of the other papers that sets the reference.
    min_batch (default 30): the fewest papers with a measure for any warning. template_characters (default none): the
    characters per text page of a template paper of continuous text, which raises the reference when it is larger.
    template_small_type (default none): the percent of the characters below 8 pt in a template paper, used likewise.
    """
    options = profile.options(CHECK)
    percentile = _whole(options.get("percentile", DEFAULT_PERCENTILE), 50, 99, "percentile")
    min_batch = _whole(options.get("min_batch", DEFAULT_MIN_BATCH), 3, None, "min_batch")
    template_characters = _number(options.get("template_characters"), "template_characters")
    template_small = _number(options.get("template_small_type"), "template_small_type")
    template_share = None if template_small is None else template_small / 100
    findings: dict[int, list[Finding]] = {paper_id: [] for paper_id in measures}
    present = {paper_id: measured for paper_id, measured in measures.items() if measured is not None}
    characters = {paper_id: m.characters for paper_id, m in present.items() if m.characters is not None}
    for paper_id, reference in _references(characters, percentile, min_batch).items():
        value, measured = characters[paper_id], present[paper_id]
        if value > max(reference, template_characters or 0) * (1 + CHARACTER_MARGIN):
            message = (f"{value:,.0f} characters per text page on the denser half of its {measured.text_pages} text "
                       f"pages, {value / reference - 1:.1%} above the {percentile}th percentile of the "
                       f"{len(characters) - 1} other papers ({reference:,.0f})")
            if template_characters:
                message += (f" and {value / template_characters - 1:.1%} above a full text page of the template "
                            f"({template_characters:,.0f})")
            message += ", possibly less space around floats and headings or smaller type on some pages"
            findings[paper_id].append(Finding(f"{CHECK}.characters", Severity.WARNING, message, measured.densest_page))
    shares = {paper_id: m.small_type for paper_id, m in present.items() if m.small_type is not None}
    for paper_id, reference in _references(shares, percentile, min_batch).items():
        value, measured = shares[paper_id], present[paper_id]
        if value > max(max(reference, template_share or 0) * SMALL_TYPE_FACTOR, MIN_SMALL_TYPE):
            message = (f"{value:.1%} of the characters of the main text below 8 pt ({measured.small:,} of "
                       f"{measured.total:,}), against {reference:.1%} at the {percentile}th percentile of the "
                       f"{len(shares) - 1} other papers")
            if template_share is not None:
                message += f" and {template_share:.1%} in the template"
            message += ", possibly captions, tables, listings, or figures set in small type"
            findings[paper_id].append(Finding(f"{CHECK}.small-type", Severity.WARNING, message,
                                              measured.small_type_page))
    return findings


def _denser_half(counts: list[int]) -> float | None:
    """Return the mean of the denser half of the character counts, which floats on the other pages leave alone."""
    if len(counts) < MIN_TEXT_PAGES:
        return None
    denser = sorted(counts, reverse=True)[: math.ceil(len(counts) / 2)]
    return sum(denser) / len(denser)


def _small_type(pdf: Path, pages: list[int]) -> tuple[int, int, int | None]:
    """Return the characters below 8 pt, all characters, and the page with the most characters below 8 pt.

    The counts take the horizontal text of the pages without the line numbers, which the review option of acmart
    prints beside the body text of each page.
    """
    try:
        with pymupdf.open(pdf) as document:
            if document.needs_pass:
                return 0, 0, None
            spans = {number: _spans(document[number - 1]) for number in pages if number <= document.page_count}
    except READ_ERRORS:
        return 0, 0, None
    sizes = Counter()
    for page in spans.values():
        for size, characters, _box, _text in page:
            sizes[round(size, 1)] += characters
    if not sizes:
        return 0, 0, None
    body = sizes.most_common(1)[0][0]
    small, total = Counter(), 0
    for number, page in spans.items():
        extent = [box for size, _characters, box, _text in page if abs(size - body) <= BODY_RANGE]
        left = min((box[0] for box in extent), default=-math.inf)
        right = max((box[2] for box in extent), default=math.inf)
        for size, characters, box, text in page:
            beside = box[2] <= left or box[0] >= right
            if size < SMALL_TYPE and beside and LINE_NUMBER.fullmatch(text.strip()):
                continue
            total += characters
            if size < SMALL_TYPE:
                small[number] += characters
    return sum(small.values()), total, small.most_common(1)[0][0] if small else None


def _spans(page: pymupdf.Page) -> list[tuple[float, int, tuple[float, float, float, float], str]]:
    """Return the size, the characters other than spaces, the box, and the text of each horizontal span of a page."""
    spans = []
    for block in page.get_text("dict", flags=pymupdf.TEXTFLAGS_TEXT)["blocks"]:
        for line in block.get("lines", ()):
            # A rotated line, such as the arXiv stamp in the margin, stands outside the text of the page.
            if line["dir"][0] <= 0.99:
                continue
            for span in line["spans"]:
                characters = sum(not char.isspace() for char in span["text"])
                if characters:
                    spans.append((span["size"], characters, tuple(span["bbox"]), span["text"]))
    return spans


def _references(values: dict[int, float], percentile: int, min_batch: int) -> dict[int, float]:
    """Return for each paper the percentile of the values of the other papers, or nothing for too small a batch."""
    if len(values) < min_batch:
        return {}
    references = {}
    for paper_id in values:
        others = [value for other, value in values.items() if other != paper_id]
        references[paper_id] = statistics.quantiles(others, n=100, method="inclusive")[percentile - 1]
    return references


def _whole(value, low: int, high: int | None, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < low or (high is not None and value > high):
        bounds = f"from {low} to {high}" if high is not None else f"of at least {low}"
        raise ProfileError(f"{CHECK}.{name} must be a whole number {bounds}")
    return value


def _number(value, name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise ProfileError(f"{CHECK}.{name} must be a number of at least 0")
    return float(value)

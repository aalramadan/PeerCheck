"""Fonts of a submission PDF, read with PyMuPDF: the font of the main text against the template of the venue, the
title size, and the fonts that are not embedded or that are Type 3 fonts.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import NamedTuple

import pymupdf

from peercheck.findings import Finding, Severity
from peercheck.models import Paper
from peercheck.profile import Profile, strings

CHECK = "fonts"
# Name prefixes of the main-text fonts of each template in IEEEtran, Word, and acmart builds, with the Times clones of
# aclpubcheck (MIT) and Liberation Serif, which sets text in the widths of Times New Roman.
TEMPLATE_FONTS = {
    "IEEE": ("NimbusRomNo9L", "Times", "TeXGyreTermes", "STIXGeneral", "LiberationSerif"),
    # ACM accepts Word papers, which need not use the Libertine fonts of acmart.
    "ACM": ("LinLibertine", "LinBiolinum", "TimesNewRoman"),
}
TITLE_TOLERANCE = 1.0
# Text within this many points counts as one size, since acmart spreads its 10 pt body over 9.9 to 10.1 pt.
SIZE_RANGE = 0.5
# MuPDF keeps 31 characters of a font name with its subset tag of seven, and a text span names the rest.
NAME_LENGTH = 24
SUBSET_TAG = re.compile(r"^[A-Z]{6}\+")
FAMILY_END = re.compile(r"[-,]")


class Span(NamedTuple):
    """A run of text in one font and one size on one page, with the characters of its whole line."""

    page: int
    font: str
    size: float
    characters: int
    line_characters: int
    horizontal: bool


def check(paper: Paper, profile: Profile, workdir: Path) -> list[Finding]:
    """Return the font findings of a paper under the options of `fonts` in the profile.

    families (default the fonts of format.style): name prefixes of the accepted main-text fonts, such as
    NimbusRomNo9L, in place of those of the template. title_size (default none): the title size in points, compared
    with the largest text on page 1. title_tolerance (default 1): the allowed difference from title_size in points.
    """
    options = profile.options(CHECK)
    families = strings(options.get("families"), f"{CHECK}.families")
    try:
        with pymupdf.open(paper.pdf) as document:
            spans = _spans(document)
            kinds = _font_kinds(document)
    except (RuntimeError, ValueError, pymupdf.mupdf.FzErrorBase):
        return [Finding(f"{CHECK}.error", Severity.WARNING, "PyMuPDF could not read the fonts of the PDF")]
    return (_template_font(spans, profile.format.style, families) + _title_size(spans, options)
            + _embedding(spans, kinds))


def _spans(document: pymupdf.Document) -> list[Span]:
    """Return the spans of every page that hold a character other than a space."""
    spans = []
    names: dict[str, str] = {}
    for number, page in enumerate(document, start=1):
        for block in page.get_text("dict", flags=pymupdf.TEXTFLAGS_TEXT)["blocks"]:
            for line in block.get("lines", ()):
                counts = [len("".join(span["text"].split())) for span in line["spans"]]
                line_characters = sum(counts)
                horizontal = line["dir"][0] > 0.99
                for span, characters in zip(line["spans"], counts):
                    if characters:
                        name = span["font"]
                        font = names.get(name) or names.setdefault(name, SUBSET_TAG.sub("", name))
                        spans.append(Span(number, font, span["size"], characters, line_characters, horizontal))
    return spans


def _font_kinds(document: pymupdf.Document) -> dict[str, str]:
    """Return each font that is a Type 3 font or that is not embedded, by its name without the subset tag."""
    kinds = {}
    for number in range(document.page_count):
        for _xref, extension, font_type, name, *_ in document.get_page_fonts(number):
            if font_type == "Type3":
                kinds[SUBSET_TAG.sub("", name)] = "type3"
            elif extension == "n/a":
                kinds[SUBSET_TAG.sub("", name)] = "not-embedded"
    return kinds


def _template_font(spans: list[Span], style: str, families: tuple[str, ...]) -> list[Finding]:
    """Return an error if a font outside the template holds more of the main text than the template fonts."""
    accepted = families or TEMPLATE_FONTS.get(style.upper(), ())
    main = _main_text(spans)
    if not accepted or not main:
        return []
    prefixes = tuple(_plain(name) for name in accepted)
    fonts = Counter()
    for span in main:
        fonts[span.font] += span.characters
    counts = Counter()
    for font, characters in fonts.items():
        family = None if _plain(font).startswith(prefixes) else FAMILY_END.split(font, maxsplit=1)[0]
        counts[family] += characters
    family, count = counts.most_common(1)[0]
    if family is None:
        return []
    source = "a font that the profile lists" if families else f"a font of the {style} template"
    message = (f"main text in {family} ({_share(count, sum(counts.values()))}), expected {source} "
               f"({', '.join(accepted)})")
    return [Finding(f"{CHECK}.template-font", Severity.ERROR, message)]


def _main_text(spans: list[Span]) -> list[Span]:
    """Return the spans within SIZE_RANGE of the size that holds the most characters."""
    sizes = Counter()
    for span in spans:
        sizes[round(span.size, 1)] += span.characters
    if not sizes:
        return []
    body = sizes.most_common(1)[0][0]
    return [span for span in spans if abs(span.size - body) <= SIZE_RANGE]


def _title_size(spans: list[Span], options: dict) -> list[Finding]:
    """Return a warning if the largest text on page 1 differs from the title size by more than the tolerance."""
    if options.get("title_size") is None:
        return []
    expected = float(options["title_size"])
    tolerance = float(options.get("title_tolerance", TITLE_TOLERANCE))
    # A drop cap stands alone on its line, and a stamp or a watermark runs at an angle.
    candidates = [span for span in spans if span.page == 1 and span.horizontal and span.line_characters > 1]
    if not candidates:
        return []
    size = max(span.size for span in candidates)
    if abs(size - expected) <= tolerance:
        return []
    title = Counter()
    for span in candidates:
        if span.size > size - SIZE_RANGE:
            title[span.font] += span.characters
    font = title.most_common(1)[0][0]
    total = sum(span.characters for span in spans)
    message = (f"largest text {size:.1f} pt in {font} ({_share(sum(title.values()), total)}), expected a title of "
               f"{expected:g} pt within {tolerance:g} pt")
    return [Finding(f"{CHECK}.title-size", Severity.WARNING, message, 1)]


def _embedding(spans: list[Span], kinds: dict[str, str]) -> list[Finding]:
    """Return a warning for each font that is not embedded and a note for each Type 3 font."""
    total = sum(span.characters for span in spans)
    findings = []
    for name, kind in sorted(kinds.items()):
        drawn = [span for span in spans if span.font[:NAME_LENGTH] == name[:NAME_LENGTH]]
        # A font that draws no character, such as one listed only in the resources, changes nothing on the page.
        if not drawn:
            continue
        share = _share(sum(span.characters for span in drawn), total)
        if kind == "type3":
            findings.append(Finding(f"{CHECK}.type3", Severity.INFO, f"Type 3 font {name} ({share})", drawn[0].page))
        else:
            findings.append(Finding(f"{CHECK}.not-embedded", Severity.WARNING, f"font {name} not embedded ({share})",
                                    drawn[0].page))
    findings.sort(key=lambda finding: finding.page)
    return findings


def _share(count: int, total: int) -> str:
    return f"{count:,} of {total:,} characters, {count / total:.1%}"


def _plain(name: str) -> str:
    return name.casefold().replace(" ", "")

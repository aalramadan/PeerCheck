"""Text that cannot be extracted from a submission PDF, found with PyMuPDF: pages whose characters carry no text and
pages covered by one image whose text is missing or does not read as English. The anonymity, reference, and
hidden-text checks read the extracted text, and such pages pass them without a finding.
"""

from __future__ import annotations

import functools
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from peercheck import tools
from peercheck.findings import Finding, Severity
from peercheck.models import Paper
from peercheck.profile import Profile

CHECK = "text"
# Without TEXT_CID_FOR_UNKNOWN_UNICODE, MuPDF returns U+FFFD for each glyph that its font maps to no Unicode
# character, where the default guesses the character from the code of the glyph.
FLAGS = pymupdf.TEXT_MEDIABOX_CLIP
# Figure labels, icons, and formulas without Unicode reach 6.5% of a page in 119 arXiv papers on software engineering,
# while body text in a font without a Unicode map fills nearly all of a page.
MIN_UNREADABLE = 50
UNREADABLE_SHARE = 0.2
# One image over 90% of the page marks a scan, a slide, or a cover, since a figure inside the margins of a
# two-column template covers about three quarters of the page.
COVER_SHARE = 0.9
# The text layer of a scan needs MIN_WORDS words to judge its language. English text holds about 40% common words,
# against 0% to 2% in German, placeholder Latin, and garbled text.
MIN_WORDS = 50
COMMON_SHARE = 0.05
# A page covered by one image with fewer words has no text to read, while a cover page shows a title and authors.
MIN_IMAGE_WORDS = 20
WORD = re.compile(r"[^\W\d_]+(?:'[^\W\d_]+)*")
SUBSET_TAG = re.compile(r"^[A-Z]{6}\+")
# MuPDF keeps 31 characters of a font name with its subset tag of seven.
NAME_LENGTH = 24
FONTS_NAMED = 3
PAGES_IN_EVIDENCE = 10


@dataclass
class PageText:
    """The characters, the words, and the largest image of one page."""

    number: int
    characters: int = 0
    unreadable: int = 0
    words: int = 0
    common: int = 0
    cover: float = 0.0
    fonts: Counter = field(default_factory=Counter)

    @property
    def garbled(self) -> bool:
        """Return True if replacement, private-use, or control characters make up much of the page."""
        return self.unreadable >= MIN_UNREADABLE and self.unreadable >= UNREADABLE_SHARE * self.characters

    @property
    def scanned(self) -> bool:
        """Return True if one image covers the page."""
        return self.cover >= COVER_SHARE

    @property
    def foreign(self) -> bool:
        """Return True if the page holds enough words to judge and few of them are common English words."""
        return self.words >= MIN_WORDS and self.common < COMMON_SHARE * self.words


def check(paper: Paper, profile: Profile, workdir: Path) -> list[Finding]:
    """Return a warning for the pages whose text is garbled and for the pages covered by one image without readable
    text.
    """
    unread = [Finding(f"{CHECK}.error", Severity.WARNING, "PyMuPDF could not read the text of the PDF")]
    try:
        with pymupdf.open(paper.pdf) as document:
            # A damaged file that needs a password may open with no page at all.
            if document.needs_pass:
                return unread
            pages = [_measure(page, number) for number, page in enumerate(document, start=1)]
            garbled = [page for page in pages if page.garbled]
            without_map = _fonts_without_map(document, garbled)
    except (RuntimeError, ValueError, pymupdf.mupdf.FzErrorBase):
        return unread
    images = [page for page in pages if page.scanned and not page.garbled]
    findings = _garbled(garbled, without_map) + _image_pages(
        [page for page in images if page.words < MIN_IMAGE_WORDS], [page for page in images if page.foreign])
    return sorted(findings, key=lambda finding: finding.page)


def _measure(page: pymupdf.Page, number: int) -> PageText:
    """Count the characters, the unreadable characters by font, and the words of a page, and find its largest image."""
    measured = PageText(number)
    lines = []
    for block in page.get_text("dict", flags=FLAGS)["blocks"]:
        for line in block.get("lines", ()):
            lines.append("".join(span["text"] for span in line["spans"]))
            for span in line["spans"]:
                unreadable = sum(_unreadable(char) for char in span["text"])
                if unreadable:
                    measured.fonts[SUBSET_TAG.sub("", span["font"])] += unreadable
                measured.unreadable += unreadable
                measured.characters += sum(not char.isspace() for char in span["text"])
    words = [word.lower() for word in WORD.findall("\n".join(lines).replace("\u2019", "'")) if len(word) > 1]
    measured.words = len(words)
    measured.common = sum(word in _common_words() for word in words)
    area = abs(page.rect)
    for image in page.get_image_info():
        # MuPDF gives the box of an image on the unrotated page.
        box = pymupdf.Rect(image["bbox"]) * page.rotation_matrix & page.rect
        if area and not box.is_empty:
            measured.cover = max(measured.cover, abs(box) / area)
    return measured


def _unreadable(char: str) -> bool:
    """Return True for a replacement, private-use, or control character, which carries no text."""
    category = unicodedata.category(char)
    return char == "\ufffd" or category == "Co" or (category == "Cc" and not char.isspace())


@functools.cache
def _common_words() -> frozenset[str]:
    """Return the English stop words of Snowball, each at the start of a line before any comment."""
    lines = tools.external("snowball/stop.txt").read_text(encoding="utf-8").splitlines()
    return frozenset(word for line in lines for word in line.split("|", 1)[0].split())


def _fonts_without_map(document: pymupdf.Document, pages: list[PageText]) -> set[str]:
    """Return the names of the fonts on the given pages whose dictionary holds no ToUnicode map."""
    names = set()
    for page in pages:
        for xref, _extension, _kind, base, *_ in document.get_page_fonts(page.number - 1):
            if document.xref_get_key(xref, "ToUnicode")[0] == "null":
                names.add(SUBSET_TAG.sub("", base)[:NAME_LENGTH])
    return names


def _garbled(pages: list[PageText], without_map: set[str]) -> list[Finding]:
    """Return one warning that names the garbled pages, their unreadable characters, and the fonts that hold them."""
    if not pages:
        return []
    unreadable = sum(page.unreadable for page in pages)
    characters = sum(page.characters for page in pages)
    fonts = Counter()
    for page in pages:
        fonts.update(page.fonts)
    named = [f"{name} (no ToUnicode map)" if name[:NAME_LENGTH] in without_map else name
             for name, _count in fonts.most_common(FONTS_NAMED)]
    message = (f"garbled text on {_page_list(pages)}, where {_share(unreadable, characters, 'characters')} are "
               f"replacement, private-use, or control characters, in {', '.join(named)}")
    evidence = "; ".join(f"page {page.number}: {_share(page.unreadable, page.characters, 'characters')}"
                         for page in pages[:PAGES_IN_EVIDENCE])
    return [Finding(f"{CHECK}.garbled", Severity.WARNING, message, pages[0].number, evidence)]


def _image_pages(blank: list[PageText], foreign: list[PageText]) -> list[Finding]:
    """Return a warning for the pages covered by one image without text and one for those with garbled text."""
    findings = []
    if blank:
        findings.append(Finding(f"{CHECK}.image-page", Severity.WARNING,
                                f"{_page_list(blank)} covered by one image, without extractable text",
                                blank[0].number))
    if foreign:
        common, words = sum(page.common for page in foreign), sum(page.words for page in foreign)
        message = (f"{_page_list(foreign)} covered by one image, with text in which {_share(common, words, 'words')} "
                   "are common English words")
        evidence = "; ".join(f"page {page.number}: {_share(page.common, page.words, 'words')}"
                             for page in foreign[:PAGES_IN_EVIDENCE])
        findings.append(Finding(f"{CHECK}.image-page", Severity.WARNING, message, foreign[0].number, evidence))
    return findings


def _page_list(pages: list[PageText]) -> str:
    """Return the page numbers in runs, such as pages 2-4, 7."""
    runs: list[list[int]] = []
    for page in pages:
        if runs and page.number == runs[-1][1] + 1:
            runs[-1][1] = page.number
        else:
            runs.append([page.number, page.number])
    text = ", ".join(str(first) if first == last else f"{first}-{last}" for first, last in runs)
    return f"page {text}" if len(pages) == 1 else f"pages {text}"


def _share(count: int, total: int, unit: str) -> str:
    return f"{count:,} of {total:,} {unit} ({count / total:.1%})"

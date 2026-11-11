"""Tests of the unreadable-text check on the fixtures of tests/fixtures/text, each built twice with pdflatex from the
LaTeX source beside it, on the paper fixtures and samples, and on small PDFs that PyMuPDF and pikepdf write.
"""

from __future__ import annotations

from pathlib import Path

import pikepdf
import pymupdf
import pytest

from peercheck.findings import Severity
from peercheck.models import Paper
from peercheck.papers import unreadable_text
from peercheck.papers.unreadable_text import PageText
from peercheck.profile import load

TEXT = Path(__file__).parent / "fixtures" / "text"
PAPERS = Path(__file__).parent / "fixtures" / "papers"
SAMPLES = Path(__file__).parents[1] / "examples" / "papers"
ENGLISH = ("Flaky tests pass and fail on the same version of the code, and a developer who sees such a failure "
           "cannot tell whether the change under review broke the program or whether the test fails at random. ")


def run(pdf: Path) -> list:
    """Run the check on a PDF under the ICSE 2027 profile."""
    return unreadable_text.check(Paper(1, pdf), load("icse-2027"), pdf.parent)


def codes(findings: list) -> list[tuple[str, Severity, int | None]]:
    """Return the check, the severity, and the page of each finding."""
    return [(f.check, f.severity, f.page) for f in findings]


def gray_page(document: pymupdf.Document, cover: float) -> pymupdf.Page:
    """Add a letter page to a document with a gray image over the given share of its width and height."""
    page = document.new_page(width=612, height=792)
    pixmap = pymupdf.Pixmap(pymupdf.csGRAY, pymupdf.IRect(0, 0, 60, 80), False)
    pixmap.clear_with(200)
    side = cover ** 0.5
    page.insert_image(pymupdf.Rect(0, 0, 612 * side, 792 * side), pixmap=pixmap)
    return page


@pytest.mark.parametrize("pdf", [TEXT / "clean.pdf", SAMPLES / "conf2027-paper1.pdf"], ids=["clean", "sample-paper"])
def test_clean_english_paper_gives_no_finding(pdf):
    assert run(pdf) == []


def test_fonts_without_tounicode_maps_whose_glyph_names_give_unicode_give_no_finding():
    assert run(TEXT / "no-tounicode.pdf") == []


def test_bitmap_type3_font_whose_glyph_names_give_the_codes_gives_no_finding():
    assert run(TEXT / "bitmap-type3.pdf") == []


@pytest.mark.parametrize("name", ["ieee-over-page-limit", "acm-small-review", "article-a4-12pt", "ieee-9pt-option"])
def test_placeholder_latin_with_readable_characters_gives_no_finding(name):
    assert run(PAPERS / f"{name}.pdf") == []


def test_letters_mapped_to_the_private_use_area_are_garbled_text_on_every_page():
    (finding,) = run(TEXT / "private-use.pdf")
    assert (finding.check, finding.severity, finding.page) == ("text.garbled", Severity.WARNING, 1)
    assert finding.message == ("garbled text on pages 1-2, where 6,502 of 6,691 characters (97.2%) are replacement, "
                               "private-use, or control characters, in NimbusRomNo9L-Regu")
    assert finding.evidence.startswith("page 1: 4,208 of 4,329 characters (97.2%); page 2: ")


def test_letters_mapped_to_the_replacement_character_are_garbled_text():
    assert codes(run(TEXT / "replacement.pdf")) == [("text.garbled", Severity.WARNING, 1)]


def test_font_without_tounicode_map_and_with_unknown_glyph_names_is_named(tmp_path):
    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(612, 792))
    names = pikepdf.Array([65] + [pikepdf.Name(f"/g{index}") for index in range(26)])
    font = pikepdf.Dictionary(Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1, BaseFont=pikepdf.Name.Helvetica,
                              Encoding=pikepdf.Dictionary(Type=pikepdf.Name.Encoding, Differences=names))
    page = pdf.pages[0]
    page.Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=pdf.make_indirect(font)))
    page.Contents = pdf.make_stream(b"BT /F1 10 Tf 72 700 Td (ABCDEFGHIJKLM NOPQRSTUVWXYZ ABCDEFGHIJKLM NOPQRSTUVWXYZ "
                                    b"ABCDEFGHIJKLM) Tj ET")
    pdf.save(tmp_path / "glyph-names.pdf")
    (finding,) = run(tmp_path / "glyph-names.pdf")
    assert finding.check == "text.garbled"
    assert finding.message.endswith("are replacement, private-use, or control characters, in Helvetica "
                                    "(no ToUnicode map)")


def test_scanned_page_without_text_layer_is_an_image_page():
    (finding,) = run(TEXT / "scanned-page.pdf")
    assert (finding.check, finding.severity, finding.page) == ("text.image-page", Severity.WARNING, 2)
    assert finding.message == "page 2 covered by one image, without extractable text"


def test_scan_whose_text_layer_does_not_read_as_english_is_an_image_page():
    (finding,) = run(TEXT / "scanned-ocr.pdf")
    assert (finding.check, finding.severity, finding.page) == ("text.image-page", Severity.WARNING, 1)
    assert finding.message == ("page 1 covered by one image, with text in which 6 of 240 words (2.5%) are common "
                               "English words")


def test_scan_with_an_english_text_layer_gives_no_finding(tmp_path):
    document = pymupdf.open()
    page = gray_page(document, 1.0)
    page.insert_textbox(pymupdf.Rect(72, 72, 540, 720), ENGLISH * 5, fontname="tiro", fontsize=10, render_mode=3)
    document.save(tmp_path / "ocr.pdf")
    assert run(tmp_path / "ocr.pdf") == []


def test_cover_page_with_a_background_image_and_a_title_gives_no_finding(tmp_path):
    document = pymupdf.open()
    page = gray_page(document, 1.0)
    page.insert_textbox(pymupdf.Rect(72, 72, 540, 300), "Research Report 8644 Dynamic Verification of Flaky Tests "
                        "with Statistical Model Checking, by Anonymous Author(s), Project Team of the Test Laboratory, "
                        "Research Center of the University", fontname="helv", fontsize=14)
    document.save(tmp_path / "cover.pdf")
    assert run(tmp_path / "cover.pdf") == []


def test_figure_inside_the_margins_is_no_image_page(tmp_path):
    document = pymupdf.open()
    gray_page(document, 0.75)
    document.save(tmp_path / "figure.pdf")
    assert run(tmp_path / "figure.pdf") == []


def test_scanned_page_turned_by_its_rotation_is_an_image_page(tmp_path):
    document = pymupdf.open()
    for rotation in (90, 270):
        gray_page(document, 1.0).set_rotation(rotation)
    document.save(tmp_path / "landscape.pdf")
    assert [f.message for f in run(tmp_path / "landscape.pdf")] == [
        "pages 1-2 covered by one image, without extractable text"]


def test_image_pages_are_listed_in_runs(tmp_path):
    document = pymupdf.open()
    for cover in (1.0, 1.0, 0.5, 1.0):
        gray_page(document, cover)
    document.save(tmp_path / "scan.pdf")
    (finding,) = run(tmp_path / "scan.pdf")
    assert (finding.page, finding.message) == (1, "pages 1-2, 4 covered by one image, without extractable text")


@pytest.mark.parametrize(("characters", "unreadable", "garbled"), [
    (1000, 199, False), (1000, 200, True), (100, 49, False), (60, 50, True),
], ids=["below-share", "at-share", "too-few", "short-page"])
def test_page_is_garbled_from_fifty_unreadable_characters_that_make_up_a_fifth(characters, unreadable, garbled):
    assert PageText(1, characters=characters, unreadable=unreadable).garbled is garbled


@pytest.mark.parametrize(("words", "common", "foreign"), [
    (49, 0, False), (50, 2, True), (100, 5, False), (400, 160, False),
], ids=["too-few-words", "two-percent", "five-percent", "english"])
def test_page_does_not_read_as_english_below_five_percent_common_words(words, common, foreign):
    assert PageText(1, words=words, common=common).foreign is foreign


def test_common_words_are_the_snowball_stop_words_without_the_comments():
    words = unreadable_text._common_words()
    assert len(words) == 174
    assert {"the", "of", "and", "which", "isn't"} <= words
    assert not {"subject", "us", "object"} & words


def test_unreadable_pdf_gives_a_warning_that_names_no_path_or_file(tmp_path):
    bad = tmp_path / "icse2027-paper7.pdf"
    bad.write_bytes(b"not a pdf at all")
    for pdf in (bad, tmp_path / "icse2027-paper8.pdf", PAPERS / "corrupt.pdf"):
        (finding,) = run(pdf)
        assert (finding.check, finding.severity) == ("text.error", Severity.WARNING)
        assert str(pdf.parent) not in finding.message and pdf.name not in finding.message


def test_pdf_locked_with_a_password_gives_a_warning(tmp_path):
    document = pymupdf.open()
    document.new_page().insert_text((72, 72), "Flaky tests pass and fail.", fontname="tiro")
    document.save(tmp_path / "locked.pdf", encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="user", owner_pw="owner")
    damaged = Path(__file__).parent / "fixtures" / "integrity" / "user-password.pdf"
    for pdf in (tmp_path / "locked.pdf", damaged):
        assert codes(run(pdf)) == [("text.error", Severity.WARNING, None)]

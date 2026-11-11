"""Tests of the fonts check on the fixtures of tests/fixtures/fonts, each built twice with pdflatex from the LaTeX
source beside it, on the paper fixtures of tests/fixtures/papers, and on small PDFs that PyMuPDF writes.
"""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path

import pymupdf
import pytest

from peercheck.findings import Severity
from peercheck.models import Paper
from peercheck.papers import fonts
from peercheck.profile import ProfileError, load

FONTS = Path(__file__).parent / "fixtures" / "fonts"
PAPERS = Path(__file__).parent / "fixtures" / "papers"
SHARE = re.compile(r"\(([\d,]+) of ([\d,]+) characters, (\d+\.\d)%\)")


def run(pdf: Path, venue: str = "icse-2027", style: str | None = None, **options) -> list:
    """Run the check on a PDF under a shipped profile with the given fonts options and, if given, format style."""
    profile = load(venue)
    profile = dataclasses.replace(profile, checks={**profile.checks, "fonts": options})
    if style is not None:
        profile = dataclasses.replace(profile, format=dataclasses.replace(profile.format, style=style))
    return fonts.check(Paper(1, pdf), profile, pdf.parent)


def codes(findings: list) -> list[tuple[str, Severity]]:
    """Return the check and the severity of each finding."""
    return [(f.check, f.severity) for f in findings]


def write_pdf(path: Path, *texts: tuple[str, float, float, str, float, int]) -> Path:
    """Write a one-page PDF with each (text, x, y, font, size, rotation) in a font of the 14 standard fonts."""
    document = pymupdf.open()
    page = document.new_page()
    for text, x, y, font, size, rotate in texts:
        page.insert_text((x, y), text, fontname=font, fontsize=size, rotate=rotate)
    document.save(path)
    return path


@pytest.mark.parametrize(("pdf", "venue", "options"), [
    (FONTS / "ieee-conference.pdf", "icse-2027", {"title_size": 24}),
    (FONTS / "acm-final.pdf", "fse-2027", {}),
    (PAPERS / "acm-small-review.pdf", "fse-2027", {}),
], ids=["ieee-conference", "acm-final", "acm-small-review"])
def test_clean_template_paper_gives_no_finding(pdf, venue, options):
    assert run(pdf, venue, **options) == []


@pytest.mark.parametrize("name", ["ieee-linespread", "ieee-over-page-limit", "ieee-refs-start-p10",
                                  "ieee-three-reference-pages"])
def test_long_ieeetran_paper_gives_no_finding(name):
    assert run(PAPERS / f"{name}.pdf", title_size=24) == []


def test_latin_modern_main_text_breaks_the_ieee_template():
    (finding,) = run(FONTS / "ieee-latin-modern.pdf")
    assert (finding.check, finding.severity, finding.page) == ("fonts.template-font", Severity.ERROR, None)
    assert finding.message.startswith("main text in LMRoman10 (")
    assert "a font of the IEEE template (NimbusRomNo9L, Times," in finding.message


def test_template_font_error_gives_the_share_of_the_main_text():
    (finding,) = run(FONTS / "ieee-latin-modern.pdf")
    count, total, percent = SHARE.search(finding.message).groups()
    assert float(percent) == round(100 * int(count.replace(",", "")) / int(total.replace(",", "")), 1) > 95


def test_article_class_paper_breaks_the_ieee_template():
    (finding,) = run(PAPERS / "article-a4-12pt.pdf")
    assert finding.check == "fonts.template-font" and "main text in CMR12 (" in finding.message


def test_acmart_paper_breaks_the_ieee_template():
    (finding,) = run(PAPERS / "acm-small-review.pdf")
    assert finding.check == "fonts.template-font" and "main text in LinLibertineT (" in finding.message


def test_main_text_spread_over_tenths_of_a_point_counts_as_one_size(tmp_path):
    # Times in the three sizes of a body under font expansion outweighs Courier, which leads at 9.9 pt alone.
    times = [("flaky tests pass and fail " * 2, 72, 100 + 14 * n, "tiro", size, 0) for n, size in
             enumerate((9.9, 10.0, 10.1))]
    pdf = write_pdf(tmp_path / "expanded.pdf", *times, ("assertEquals(cache.size()); " * 2, 72, 160, "cour", 9.9, 0))
    assert "fonts.template-font" not in {f.check for f in run(pdf)}


def test_times_of_the_standard_fonts_counts_as_the_ieee_template(tmp_path):
    pdf = write_pdf(tmp_path / "times.pdf", ("Flaky tests pass and fail on the same code.", 72, 72, "tiro", 10, 0))
    assert codes(run(pdf)) == [("fonts.not-embedded", Severity.WARNING)]


def test_families_of_the_profile_replace_the_template_fonts():
    assert run(FONTS / "ieee-latin-modern.pdf", families=["LMRoman"]) == []
    (finding,) = run(FONTS / "ieee-conference.pdf", families=["LMRoman"])
    assert finding.message.startswith("main text in NimbusRomNo9L (")
    assert finding.message.endswith("expected a font that the profile lists (LMRoman)")


def test_families_accept_one_string_without_regard_to_case_or_spaces():
    assert run(FONTS / "ieee-latin-modern.pdf", families="lm roman") == []


def test_families_that_are_no_strings_raise():
    with pytest.raises(ProfileError):
        run(FONTS / "ieee-conference.pdf", families={"name": "LMRoman"})


def test_style_without_template_fonts_skips_the_font_comparison():
    assert run(PAPERS / "article-a4-12pt.pdf", style="LNCS") == []


def test_title_below_the_size_of_the_profile_is_a_warning():
    (finding,) = run(FONTS / "ieee-small-title.pdf", title_size=24)
    assert (finding.check, finding.severity, finding.page) == ("fonts.title-size", Severity.WARNING, 1)
    assert finding.message.startswith("largest text 16.9 pt in NimbusRomNo9L-Regu (48 of ")
    assert finding.message.endswith("expected a title of 24 pt within 1 pt")


def test_title_within_the_tolerance_of_the_profile_passes():
    assert codes(run(PAPERS / "ieee-9pt-option.pdf", title_size=24)) == [("fonts.title-size", Severity.WARNING)]
    assert run(PAPERS / "ieee-9pt-option.pdf", title_size=24, title_tolerance=5) == []


def test_title_size_is_not_compared_without_a_size_in_the_profile():
    assert run(FONTS / "ieee-small-title.pdf") == []


def test_drop_cap_and_rotated_stamp_are_not_taken_for_the_title(tmp_path):
    pdf = write_pdf(tmp_path / "title.pdf", ("A Title in Twenty-Four Points", 72, 80, "tiro", 24, 0),
                    ("F", 72, 300, "tiro", 30, 0), ("arXiv:2601.00001v1 [cs.SE] 5 Jan 2026", 30, 700, "tiro", 30, 90))
    assert "fonts.title-size" not in {f.check for f in run(pdf, title_size=24)}


def test_font_that_is_not_embedded_is_a_warning_with_its_share():
    (finding,) = run(FONTS / "ieee-unembedded.pdf")
    assert (finding.check, finding.severity, finding.page) == ("fonts.not-embedded", Severity.WARNING, 1)
    assert finding.message.startswith("font Helvetica not embedded (13 of ")
    assert SHARE.search(finding.message)


def test_type3_font_is_an_info_note_with_its_share():
    (finding,) = run(FONTS / "ieee-type3.pdf")
    assert (finding.check, finding.severity, finding.page) == ("fonts.type3", Severity.INFO, 1)
    assert finding.message.startswith("Type 3 font F32 (7 of ")


def test_font_that_draws_no_character_gives_no_finding(tmp_path):
    document = pymupdf.open()
    page = document.new_page()
    page.insert_font(fontname="helv")
    page.insert_text((72, 72), "Flaky tests pass and fail on the same code.", fontname="tiro", fontsize=10)
    document.save(tmp_path / "unused.pdf")
    (finding,) = run(tmp_path / "unused.pdf")
    assert finding.message.startswith("font Times-Roman not embedded")


def test_unreadable_pdf_gives_a_warning_that_names_no_path_or_file(tmp_path):
    bad = tmp_path / "icse2027-paper7.pdf"
    bad.write_bytes(b"not a pdf at all")
    for pdf in (bad, tmp_path / "icse2027-paper8.pdf", PAPERS / "corrupt.pdf"):
        (finding,) = run(pdf)
        assert (finding.check, finding.severity) == ("fonts.error", Severity.WARNING)
        assert str(pdf.parent) not in finding.message and pdf.name not in finding.message


def test_pdf_locked_with_a_password_gives_a_warning(tmp_path):
    document = pymupdf.open()
    document.new_page().insert_text((72, 72), "Flaky tests pass and fail.", fontname="tiro")
    document.save(tmp_path / "locked.pdf", encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="user", owner_pw="owner")
    assert codes(run(tmp_path / "locked.pdf")) == [("fonts.error", Severity.WARNING)]

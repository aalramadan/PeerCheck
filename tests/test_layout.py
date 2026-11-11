"""Tests of the banal format check: page counts, format rules, and unreadable PDFs."""

import dataclasses
import json
import shutil
import subprocess
from pathlib import Path

import pymupdf
import pytest

from peercheck import profile, tools
from peercheck.findings import Severity
from peercheck.models import Paper
from peercheck.papers import layout

PAPERS = Path(__file__).parent / "fixtures" / "papers"
needs_banal = pytest.mark.skipif(not (shutil.which("perl") and shutil.which("pdftohtml")),
                                 reason="banal needs perl and pdftohtml")


def _inspect(name):
    return layout.inspect(Paper(1, PAPERS / name), profile.load("icse-2027"))


def _checks(result):
    return {f.check for f in result.findings}


def _flagged(result):
    return [(f.check, f.severity) for f in result.findings if f.severity is not Severity.INFO]


@needs_banal
def test_references_starting_on_page_ten_with_two_reference_pages_pass():
    result = _inspect("ieee-refs-start-p10.pdf")
    assert (result.layout.total_pages, result.layout.main_pages, result.layout.reference_pages) == (12, 10, 2)
    assert result.layout.references_start == 10
    assert not [f for f in result.findings if f.severity is not Severity.INFO]


@needs_banal
def test_three_reference_only_pages_break_the_limit():
    assert "layout.reference-pages" in _checks(_inspect("ieee-three-reference-pages.pdf"))


@needs_banal
def test_main_text_over_ten_pages_breaks_the_limit():
    assert "layout.main-pages" in _checks(_inspect("ieee-over-page-limit.pdf"))


@needs_banal
def test_a4_one_column_draft_breaks_the_format_rules():
    checks = _checks(_inspect("article-a4-12pt.pdf"))
    assert {"layout.paper-size", "layout.body-font", "layout.columns", "layout.margins"} <= checks
    assert "layout.no-references" not in checks


@needs_banal
def test_page_numbers_are_a_warning_under_the_example_profile():
    finding = next(f for f in _inspect("article-a4-12pt.pdf").findings if f.check == "layout.page-numbers")
    assert finding.severity is Severity.WARNING


@needs_banal
def test_unreadable_pdf_gives_a_warning_and_no_layout():
    result = _inspect("corrupt.pdf")
    assert result.layout is None
    assert [f.check for f in result.findings] == ["layout.error"]


def test_ieee_headings_with_roman_numerals_satisfy_the_required_headings():
    report = {"pages": [{"headings": ["A Title", "I. INTRODUCTION"]}, {"headings": ["VI. CONCLUSION", "REFERENCES"]}],
              "w": 2000, "papersize": [792, 612], "columns": 2}
    findings = layout.evaluate(layout.measure(report), profile.load("icse-2027").format, "Abstract—We study")
    assert not [f for f in findings if f.check in ("layout.missing-heading", "layout.missing-abstract")]


def test_missing_conclusion_and_abstract_are_warnings():
    report = {"pages": [{"headings": ["1 Introduction"]}, {"headings": ["2 Results"]}], "w": 2000}
    findings = layout.evaluate(layout.measure(report), profile.load("icse-2027").format, "Summary text")
    assert {(f.check, f.severity) for f in findings} >= {
        ("layout.missing-heading", Severity.WARNING), ("layout.missing-abstract", Severity.WARNING)}


def test_reference_pages_count_only_bib_pages_from_the_references_heading_on():
    pages = [{}, {}, {"headings": ["REFERENCES"]}, {"type": "bib"}, {"type": "appendix"}]
    measured = layout.measure({"pages": pages, "w": 5000})
    assert (measured.references_start, measured.reference_pages, measured.main_pages) == (3, 1, 4)


def test_measure_keeps_the_type_and_the_characters_of_each_page():
    pages = [{"c": 4900}, {"c": 6400}, {"type": "figure", "c": 500}, {"type": "blank"}, {"type": "bib", "c": 8100}]
    measured = layout.measure({"pages": pages, "w": 5000})
    assert measured.page_types == ["body", "body", "figure", "blank", "bib"]
    assert (measured.page_characters, measured.characters) == ([4900, 6400, 500, 0, 8100], 19900)


def test_landscape_pages_read_as_slides():
    findings = layout.evaluate(layout.measure({"pages": [{}], "papersize": [612, 792], "w": 900}),
                               profile.load("icse-2027").format, None)
    assert any("landscape" in f.message for f in findings)


@needs_banal
def test_acmart_review_paper_passes_the_fse_profile():
    result = layout.inspect(Paper(1, PAPERS / "acm-small-review.pdf"), profile.load("fse-2027"))
    assert not [f for f in result.findings if f.severity is not Severity.INFO]


@needs_banal
def test_acmart_paper_breaks_the_ieee_profile():
    checks = {f.check for f in _inspect("acm-small-review.pdf").findings}
    assert {"layout.paper-size", "layout.columns"} <= checks


@needs_banal
def test_nine_point_body_font_breaks_the_lower_limit():
    assert _flagged(_inspect("ieee-9pt-option.pdf")) == [("layout.body-font", Severity.ERROR)]


@needs_banal
def test_squeezed_line_spacing_breaks_the_lower_limit():
    assert _flagged(_inspect("ieee-linespread.pdf")) == [("layout.line-spacing", Severity.ERROR)]


def test_line_spacing_comes_from_the_pages_of_the_main_text():
    # banal gives the whole PDF the spacing of the reference pages when these win a tie with the body pages.
    pages = [{"leading": 12}, {"leading": 12, "headings": ["REFERENCES"]}, {"type": "bib"}, {"type": "bib"}]
    measured = layout.measure({"pages": pages, "leading": 9.1, "w": 2000})
    assert measured.leading == 12
    rules = profile.load("icse-2027").format
    assert not [f for f in layout.evaluate(measured, rules, "Abstract") if f.check == "layout.line-spacing"]


def test_page_turned_for_reading_keeps_the_paper_size():
    turned = layout.measure({"papersize": [792, 612], "pages": [{}, {"papersize": [612, 792]}], "w": 1800})
    a4 = layout.measure({"papersize": [792, 612], "pages": [{}, {"papersize": [842, 595]}], "w": 1800})
    assert (turned.mixed_paper_sizes, a4.mixed_paper_sizes) == (False, True)


@needs_banal
def test_pdf_with_a_page_turned_for_reading_has_no_mixed_paper_sizes(tmp_path):
    with pymupdf.open(PAPERS / "ieee-refs-start-p10.pdf") as document:
        document[4].set_rotation(90)
        document.save(tmp_path / "turned.pdf")
    result = layout.inspect(Paper(1, tmp_path / "turned.pdf"), profile.load("icse-2027"))
    assert "layout.mixed-paper-sizes" not in _checks(result)


def test_pdf_of_which_poppler_reads_no_pages_gives_a_warning(monkeypatch):
    empty = json.dumps({"papersize": [0, 0], "margin": [0, 0, 0, 0], "w": 0, "pages": []})
    monkeypatch.setattr(tools, "program", lambda name: name)
    monkeypatch.setattr(layout.subprocess, "run",
                        lambda command, **kwargs: subprocess.CompletedProcess(command, 0, empty, ""))
    result = _inspect("ieee-over-page-limit.pdf")
    assert result.layout is None
    assert [f.check for f in result.findings] == ["layout.error"]


@needs_banal
def test_copy_protected_pdf_gets_the_page_limit_check(tmp_path):
    with pymupdf.open(PAPERS / "ieee-over-page-limit.pdf") as document:
        document.save(tmp_path / "protected.pdf", encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="secret",
                      user_pw="", permissions=pymupdf.PDF_PERM_PRINT)
    checks = _checks(layout.inspect(Paper(1, tmp_path / "protected.pdf"), profile.load("icse-2027")))
    assert "layout.main-pages" in checks
    assert "layout.error" not in checks


@needs_banal
def test_pdf_whose_name_starts_with_a_dash_reaches_banal_as_a_file(tmp_path, monkeypatch):
    shutil.copyfile(PAPERS / "ieee-refs-start-p10.pdf", tmp_path / "-paper2.pdf")
    monkeypatch.chdir(tmp_path)
    result = layout.inspect(Paper(2, Path("-paper2.pdf")), profile.load("icse-2027"))
    assert result.layout is not None


@needs_banal
def test_banal_error_names_no_path_or_file_of_the_pdf(tmp_path):
    shutil.copyfile(PAPERS / "corrupt.pdf", tmp_path / "icse2027-paper9.pdf")
    (finding,) = layout.inspect(Paper(9, tmp_path / "icse2027-paper9.pdf"), profile.load("icse-2027")).findings
    assert finding.check == "layout.error"
    assert str(tmp_path) not in finding.message and "icse2027-paper9" not in finding.message


def _pages_with_statement(statement_pages):
    """Return banal pages of 18 body pages, a statement on the next pages, and one page of references."""
    pages = [{"headings": ["I. INTRODUCTION"]}] + [{} for _ in range(17)]
    pages += [{"headings": ["8 DATA AVAILABILITY"]}] + [{} for _ in range(statement_pages - 1)]
    return pages + [{"type": "bib", "headings": ["REFERENCES"]}]


def test_pages_after_an_exempt_section_heading_do_not_count_as_main_text():
    measured = layout.measure({"pages": _pages_with_statement(3), "w": 20000}, ("data availability",))
    assert (measured.exempt_start, measured.exempt_pages, measured.main_pages) == (19, 2, 19)


def test_exempt_section_longer_than_the_profile_allows_is_a_warning():
    measured = layout.measure({"pages": _pages_with_statement(3), "w": 20000}, ("data availability",))
    rules = dataclasses.replace(profile.load("fse-2027").format, main_pages=19, exempt_pages_max=1)
    found = [(f.check, f.severity) for f in layout.evaluate(measured, rules, "Abstract")]
    assert ("layout.exempt-pages", Severity.WARNING) in found


def test_exempt_section_that_opens_its_page_frees_that_page_too(tmp_path):
    pdf = tmp_path / "statement.pdf"
    document = pymupdf.open()
    opened = document.new_page()
    opened.insert_text((72, 120), "8 Data Availability")
    opened.insert_text((72, 140), "The artifact is available on Zenodo.")
    shared = document.new_page()
    shared.insert_text((72, 120), "and the results hold in every project.")
    shared.insert_text((72, 160), "8 Data Availability")
    document.save(pdf)
    document.close()
    assert layout.opens_page(pdf, 1, ("data availability",), top=84)
    assert not layout.opens_page(pdf, 2, ("data availability",), top=84)


def test_fse_profile_exempts_the_data_availability_section():
    rules = profile.load("fse-2027").format
    assert rules.exempt_sections == ("data availability",) and rules.exempt_pages_max == 1

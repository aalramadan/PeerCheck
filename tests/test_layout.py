"""Tests of the banal format check: page counts, format rules, and unreadable PDFs."""

import shutil
from pathlib import Path

import pytest

from peercheck import profile
from peercheck.checks import layout
from peercheck.findings import Severity
from peercheck.models import Paper

PAPERS = Path(__file__).parent / "fixtures" / "papers"
needs_banal = pytest.mark.skipif(not (shutil.which("perl") and shutil.which("pdftohtml")),
                                 reason="banal needs perl and pdftohtml")


def _inspect(name):
    return layout.inspect(Paper(1, PAPERS / name), profile.load("conf-2026"))


def _checks(result):
    return {f.check for f in result.findings}


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
def test_page_numbers_are_a_warning_under_the_conf_profile():
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
    findings = layout.evaluate(layout.measure(report), profile.load("conf-2026").format, "Abstract—We study")
    assert not [f for f in findings if f.check in ("layout.missing-heading", "layout.missing-abstract")]


def test_missing_conclusion_and_abstract_are_warnings():
    report = {"pages": [{"headings": ["1 Introduction"]}, {"headings": ["2 Results"]}], "w": 2000}
    findings = layout.evaluate(layout.measure(report), profile.load("conf-2026").format, "Summary text")
    assert {(f.check, f.severity) for f in findings} >= {
        ("layout.missing-heading", Severity.WARNING), ("layout.missing-abstract", Severity.WARNING)}


def test_reference_pages_count_only_bib_pages_from_the_references_heading_on():
    pages = [{}, {}, {"headings": ["REFERENCES"]}, {"type": "bib"}, {"type": "appendix"}]
    measured = layout.measure({"pages": pages, "w": 5000})
    assert (measured.references_start, measured.reference_pages, measured.main_pages) == (3, 1, 4)


def test_landscape_pages_read_as_slides():
    findings = layout.evaluate(layout.measure({"pages": [{}], "papersize": [612, 792], "w": 900}),
                               profile.load("conf-2026").format, None)
    assert any("landscape" in f.message for f in findings)


@needs_banal
def test_acmart_review_paper_passes_the_fse_profile():
    result = layout.inspect(Paper(1, PAPERS / "acm-small-review.pdf"), profile.load("fse-2027"))
    assert not [f for f in result.findings if f.severity is not Severity.INFO]


@needs_banal
def test_acmart_paper_breaks_the_ieee_profile():
    checks = {f.check for f in _inspect("acm-small-review.pdf").findings}
    assert {"layout.paper-size", "layout.columns"} <= checks

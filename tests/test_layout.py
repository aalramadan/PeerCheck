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
LAYOUT = Path(__file__).parent / "fixtures" / "layout"
MARGINS = Path(__file__).parent / "fixtures" / "margins"
needs_banal = pytest.mark.skipif(not (shutil.which("perl") and shutil.which("pdftohtml")),
                                 reason="banal needs perl and pdftohtml")


def _inspect(name):
    return layout.inspect(Paper(1, PAPERS / name), profile.load("icse-2027"))


def _inspect_layout(name):
    return layout.inspect(Paper(1, LAYOUT / name), profile.load("icse-2027"))


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
    assert {"layout.paper-size", "layout.body-font", "layout.columns"} <= checks
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


def _margin_findings(margins, template="icse-2027"):
    report = {"pages": [{}], "w": 900, "margin": margins}
    found = layout.evaluate(layout.measure(report), profile.load(template).format, "Abstract")
    return [(f.check, f.severity, f.message) for f in found if f.check == "layout.margins"]


def test_margin_narrower_than_the_template_beyond_the_tolerance_is_an_error():
    assert _margin_findings([52, 48, 53, 48]) == [("layout.margins", Severity.ERROR, (
        "margins 52, 48, 53, 48 pt, narrower than the 52, 48, 72, 48 pt of the template by more than 18 pt"))]
    assert _margin_findings([52, 48, 54, 30]) == []


def test_margins_wider_than_the_template_break_no_rule():
    assert _margin_findings([76, 72, 108, 72]) == []


@needs_banal
def test_wide_text_block_breaks_the_margins_of_the_template():
    result = layout.inspect(Paper(1, MARGINS / "ieee-wide-text.pdf"), profile.load("icse-2027"))
    assert "layout.margins" in _checks(result)


@needs_banal
def test_acmsmall_paper_without_the_review_option_keeps_the_margins_of_the_fse_profile():
    result = layout.inspect(Paper(1, MARGINS / "acm-clean.pdf"), profile.load("fse-2027"))
    assert "layout.margins" not in _checks(result)


def test_fse_profile_allows_a_running_head_that_banal_counts_as_text_and_nothing_narrower():
    assert _margin_findings([60, 42, 36, 44], "fse-2027") == []
    assert [check for check, _, _ in _margin_findings([59, 42, 36, 44], "fse-2027")] == ["layout.margins"]
    assert [check for check, _, _ in _margin_findings([84, 42, 36, 19], "fse-2027")] == ["layout.margins"]


@needs_banal
def test_acmart_abstract_without_a_label_counts_as_an_abstract():
    assert "layout.missing-abstract" not in _checks(_inspect_layout("acm-unlabeled-abstract.pdf"))


@needs_banal
def test_acmart_paper_without_an_abstract_is_a_warning():
    assert "layout.missing-abstract" in _checks(_inspect_layout("acm-no-abstract.pdf"))


def _lacks_abstract(first_page):
    found = layout.evaluate(layout.measure({"pages": [{}], "w": 900}), profile.load("icse-2027").format, first_page)
    return "layout.missing-abstract" in {f.check for f in found}


def _first_page(lines, words, follows="1 Introduction"):
    """Return the text of a first page with a title, lines of text without a label, and what follows them."""
    text = "\n".join(" ".join(["flaky"] * words) for _ in range(lines))
    return f"Ranking Flaky Test Failures\nAnonymous Author(s)\n{text}\n{follows}\nFlaky tests pass and fail.\n"


@pytest.mark.parametrize("follows", [
    "CCS Concepts: \u2022 Software and its engineering \u2192 Software testing and debugging.",
    "Additional Key Words and Phrases: flaky tests, regression testing", "ACM Reference Format:",
    "1 Introduction", "1\nINTRODUCTION", "I. INTRODUCTION", "Introduction",
], ids=["ccs-concepts", "key-words", "reference-format", "number", "number-on-its-own-line", "roman-number",
        "no-number"])
def test_abstract_without_a_label_ends_at_the_top_matter_of_acmart_or_at_the_introduction(follows):
    assert not _lacks_abstract(_first_page(10, 13, follows))


@pytest.mark.parametrize(("lines", "words", "missing"), [
    (10, 13, False), (9, 13, True), (17, 8, False), (20, 7, True),
], ids=["130-words", "117-words", "lines-of-8-words", "lines-of-7-words"])
def test_abstract_without_a_label_takes_130_words_in_lines_of_8_words_or_more(lines, words, missing):
    assert _lacks_abstract(_first_page(lines, words)) is missing


def test_author_blocks_above_the_first_section_are_no_abstract():
    author = ("Jane Example\nDepartment of Computer Science and Engineering\nExample University\n"
              "Example City, Exampleland\njane@example.org\n")
    assert _lacks_abstract(f"Ranking Flaky Test Failures\n{author * 12}I. INTRODUCTION\nFlaky tests pass and fail.\n")


def test_rows_of_numbers_above_the_first_section_are_no_lines_of_an_abstract():
    rows = "\n".join(" ".join(str(row * 10 + column) for column in range(10)) for row in range(20))
    assert _lacks_abstract(f"Ranking Flaky Test Failures\nAnonymous Author(s)\n{rows}\n1\nIntroduction\n")


def test_heading_in_another_form_of_the_word_satisfies_the_required_heading():
    report = {"pages": [{"headings": ["1 Introduction"]}, {"headings": ["9 Concluding Remarks"]}], "w": 2000}
    found = layout.evaluate(layout.measure(report), profile.load("icse-2027").format, "Abstract")
    assert "layout.missing-heading" not in {f.check for f in found}


def test_heading_of_another_word_does_not_satisfy_the_required_heading():
    report = {"pages": [{"headings": ["1 Introduction"]}, {"headings": ["9 Future Plans", "Concepts"]}], "w": 2000}
    found = layout.evaluate(layout.measure(report), profile.load("icse-2027").format, "Abstract")
    assert [f.message for f in found if f.check == "layout.missing-heading"] == ["no heading containing 'conclusion'"]


def test_short_required_heading_is_not_satisfied_by_another_form_of_the_word():
    rules = dataclasses.replace(profile.load("icse-2027").format, required_headings=("introduction", "threats"))
    report = {"pages": [{"headings": ["1 Introduction", "2 Threat Model"]}, {"headings": ["6 Conclusion"]}], "w": 2000}
    found = layout.evaluate(layout.measure(report), rules, "Abstract")
    assert [f.message for f in found if f.check == "layout.missing-heading"] == ["no heading containing 'threats'"]


def _without_heading(pdf, heading, monkeypatch):
    """Inspect a PDF under the ICSE 2027 profile as if banal had missed one of its headings."""
    report = layout.run_banal(pdf)
    for page in report["pages"]:
        page["headings"] = [name for name in page.get("headings", []) if heading not in name.lower()]
    monkeypatch.setattr(layout, "run_banal", lambda pdf: report)
    return layout.inspect(Paper(1, pdf), profile.load("icse-2027"))


@needs_banal
def test_heading_that_banal_missed_is_found_in_the_text_of_the_pdf(monkeypatch):
    result = _without_heading(LAYOUT / "ieee-year-ends-page.pdf", "conclusion", monkeypatch)
    assert "layout.missing-heading" not in _checks(result)


@needs_banal
def test_heading_that_the_pdf_does_not_hold_stays_missing():
    icse = profile.load("icse-2027")
    rules = dataclasses.replace(icse.format, required_headings=("introduction", "threats"))
    result = layout.inspect(Paper(1, LAYOUT / "ieee-year-ends-page.pdf"), dataclasses.replace(icse, format=rules))
    assert [f.message for f in result.findings if f.check == "layout.missing-heading"] == [
        "no heading containing 'threats'"]


@needs_banal
def test_table_caption_in_capital_letters_is_no_section_heading():
    result = _inspect_layout("ieee-capital-caption.pdf")
    assert [f.message for f in result.findings if f.check == "layout.missing-heading"] == [
        "no heading containing 'conclusion'"]


def _inspect_drawn(tmp_path, monkeypatch, draw, pages=1, **measures):
    """Inspect a PDF whose pages the draw function fills, given each page and its number, under the ICSE 2027
    profile, as if banal had found its Introduction and the given measures."""
    with pymupdf.open() as document:
        for number in range(1, pages + 1):
            draw(document.new_page(), number)
        document.save(tmp_path / "paper.pdf")
    report = {"pages": [{"headings": ["I. INTRODUCTION"]}, *[{}] * (pages - 1)], "w": 900 * pages, **measures}
    monkeypatch.setattr(layout, "run_banal", lambda pdf: report)
    return layout.inspect(Paper(1, tmp_path / "paper.pdf"), profile.load("icse-2027"))


@pytest.mark.parametrize(("line", "missing"), [
    ("VI. LESSONS, THREATS TO VALIDITY AND CONCLUSION", False),
    ("CONCLUSIONS OF EARLIER STUDIES", True),
    ("I. Conclusions of the earlier studies differ, as the next section shows.", True),
], ids=["numbered-capitals", "capitals-without-a-number", "numbered-sentence"])
def test_only_a_numbered_line_in_capital_letters_is_a_heading_that_banal_missed(tmp_path, monkeypatch, line, missing):
    def draw(page, number):
        page.insert_text((72, 100), "The studies of flaky tests reach the results of Table", fontsize=10)
        page.insert_text((72, 114), line, fontsize=10)

    result = _inspect_drawn(tmp_path, monkeypatch, draw)
    assert ("layout.missing-heading" in _checks(result)) is missing


@needs_banal
def test_year_that_ends_a_page_is_no_page_number():
    result = _inspect_layout("ieee-year-ends-page.pdf")
    assert "layout.page-numbers" not in _checks(result)
    assert result.layout.page_number_margin is None


@needs_banal
def test_page_numbers_that_count_up_below_the_text_are_reported():
    result = layout.inspect(Paper(1, MARGINS / "ieee-clean.pdf"), profile.load("icse-2027"))
    assert "layout.page-numbers" in _checks(result)


def _footer(form):
    """Return a function that draws a line of body text and the footer that the form gives for the page, if any."""
    def draw(page, number):
        page.insert_text((72, 100), "The ranking places a flaky failure first.", fontsize=10)
        if form(number):
            page.insert_text((300, 760), form(number), fontsize=8)
    return draw


@pytest.mark.parametrize(("form", "pages", "reported"), [
    (str, 4, True),
    (lambda number: f"{number}/4", 4, True),
    (lambda number: str(number) if number > 1 else None, 2, True),
    (lambda number: "2026", 4, False),
    (lambda number: "2026" if number > 1 else None, 2, False),
    (lambda number: str(number) if number in (2, 3) else None, 5, False),
], ids=["number", "number-and-page-count", "none-on-the-title-page", "same-number-on-each-page", "one-year",
        "on-two-of-five-pages"])
def test_numbers_below_the_text_are_page_numbers_where_they_count_up_with_the_pages(
        tmp_path, monkeypatch, form, pages, reported):
    result = _inspect_drawn(tmp_path, monkeypatch, _footer(form), pages, nummargin=30)
    assert ("layout.page-numbers" in _checks(result)) is reported
    assert (result.layout.page_number_margin is not None) is reported


def test_page_number_between_dashes_of_a_larger_type_is_reported(tmp_path, monkeypatch):
    def draw(page, number):
        page.insert_text((72, 100), "The ranking places a flaky failure first.", fontsize=10)
        page.insert_text((290, 760), "-", fontsize=12)
        page.insert_text((300, 760), str(number), fontsize=8)
        page.insert_text((310, 760), "-", fontsize=12)

    assert "layout.page-numbers" in _checks(_inspect_drawn(tmp_path, monkeypatch, draw, pages=4, nummargin=30))


def test_page_numbers_of_banal_stay_for_a_pdf_that_only_banal_reads(tmp_path, monkeypatch):
    pdf = tmp_path / "paper.pdf"
    pdf.write_text("no PDF", encoding="utf-8")
    monkeypatch.setattr(layout, "run_banal", lambda pdf: {"pages": [{}], "w": 900, "nummargin": 30})
    assert "layout.page-numbers" in _checks(layout.inspect(Paper(1, pdf), profile.load("icse-2027")))

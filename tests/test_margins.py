"""Tests of the margin check on the LaTeX fixtures of tests/fixtures/margins and on PDFs drawn with PyMuPDF."""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path

import pymupdf
import pytest

from peercheck.findings import Severity
from peercheck.models import Paper
from peercheck.papers import margins
from peercheck.profile import load

TESTS = Path(__file__).parent
FIXTURES = TESTS / "fixtures" / "margins"
PAPERS = TESTS / "fixtures" / "papers"
SAMPLES = TESTS.parent / "examples" / "papers"
CLEAN = [
    *[(path, "icse-2027") for path in sorted(SAMPLES.glob("*.pdf"))],
    *[(path, "icse-2027") for path in sorted(PAPERS.glob("*.pdf")) if path.stem.startswith(("ieee-", "article-"))],
    (PAPERS / "acm-small-review.pdf", "fse-2027"),
    (FIXTURES / "ieee-clean.pdf", "icse-2027"),
    (FIXTURES / "acm-clean.pdf", "fse-2027"),
]


def run(pdf: Path, profile_key: str = "icse-2027", **options) -> list:
    """Run the check on one PDF with the given margins options of a shipped profile."""
    profile = load(profile_key)
    if options:
        profile = dataclasses.replace(profile, checks={**profile.checks, "margins": options})
    return margins.check(Paper(1, pdf), profile, pdf.parent)


def reach(finding, side: str) -> float:
    """Return how far a finding says the content runs into the margin of one side."""
    return float(re.search(rf"([\d.]+) pt into the {side} margin", finding.message).group(1))


def write_pdf(path: Path, draw, pages: int = 1, size: tuple[float, float] = (612, 792), rotation: int = 0) -> Path:
    """Write a PDF whose pages the draw function fills, given each page and its index, and return its path."""
    with pymupdf.open() as document:
        for number in range(pages):
            page = document.new_page(width=size[0], height=size[1])
            draw(page, number)
            page.set_rotation(rotation)
        document.save(path)
    return path


def gray_image(page: pymupdf.Page, rect: tuple[float, float, float, float], level: int = 90) -> None:
    """Place an image of one gray level over the rectangle."""
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 8, 8), False)
    pixmap.set_rect(pixmap.irect, (level, level, level))
    page.insert_image(pymupdf.Rect(rect), pixmap=pixmap, keep_proportion=False)


@pytest.mark.parametrize(("pdf", "profile_key"), CLEAN, ids=lambda value: getattr(value, "name", value))
def test_clean_template_papers_give_no_finding(pdf, profile_key):
    assert run(pdf, profile_key) == []


def test_review_pages_with_line_numbers_and_running_heads_give_no_finding():
    assert [finding.page for finding in run(FIXTURES / "acm-review.pdf", "fse-2027")] == [4]


def test_figure_past_the_line_numbers_reports_how_far_its_ink_reaches():
    (finding,) = run(FIXTURES / "acm-review.pdf", "fse-2027")
    assert (finding.check, finding.severity) == ("margins.overflow", Severity.ERROR)
    assert finding.message.startswith("content (image) runs")
    assert reach(finding, "left") == pytest.approx(30.2, abs=1)


def test_table_wider_than_the_text_runs_into_the_right_margin():
    (finding,) = run(FIXTURES / "ieee-wide-table.pdf")
    assert (finding.check, finding.severity, finding.page) == ("margins.overflow", Severity.ERROR, 2)
    assert reach(finding, "right") == pytest.approx(39, abs=1)
    assert "text, drawing" in finding.message
    assert "Total" in finding.evidence


def test_overshoot_within_the_tolerance_gives_no_finding():
    found = {finding.page: finding for finding in run(FIXTURES / "ieee-wide-table.pdf", tolerance=0)}
    assert reach(found[3], "right") == pytest.approx(5, abs=1)
    assert [finding.page for finding in run(FIXTURES / "ieee-wide-table.pdf")] == [2]


def test_tolerance_option_sets_the_limit():
    assert run(FIXTURES / "ieee-wide-table.pdf", tolerance=40) == []
    assert len(run(FIXTURES / "ieee-wide-table.pdf", tolerance=30)) == 1


def test_figure_wider_than_the_text_runs_into_both_side_margins():
    (finding,) = run(FIXTURES / "ieee-wide-figure.pdf")
    assert finding.page == 2
    assert reach(finding, "right") == pytest.approx(25.7, abs=1)
    assert reach(finding, "left") == pytest.approx(25.7, abs=1)


def test_white_background_box_in_the_margins_gives_no_finding():
    found = run(FIXTURES / "ieee-wide-figure.pdf", tolerance=0)
    assert not [finding for finding in found if finding.page == 3 and re.search("left|right", finding.message)]


def test_widened_text_block_gives_one_finding_that_names_each_side():
    (finding,) = run(FIXTURES / "ieee-wide-text.pdf")
    assert finding.page == 1
    assert reach(finding, "bottom") == pytest.approx(23, abs=1.5)
    assert reach(finding, "left") == pytest.approx(23, abs=1)


def test_text_in_the_margin_gives_its_page_side_and_distance_without_the_file_name(tmp_path):
    def draw(page, number):
        page.insert_text((72, 100), "Body text inside the text block.", fontsize=10)
        if number == 1:
            page.insert_text((570, 300), "note", fontsize=10)

    pdf = write_pdf(tmp_path / "icse2027-paper7.pdf", draw, pages=2)
    (finding,) = run(pdf)
    assert finding.page == 2
    assert 20 < reach(finding, "right") < 30
    assert finding.evidence == "note"
    assert pdf.name not in finding.message + finding.evidence
    assert str(tmp_path) not in finding.message + finding.evidence


def test_invisible_text_and_blank_boxes_in_the_margin_give_no_finding(tmp_path):
    def draw(page, number):
        page.insert_text((575, 300), "white", fontsize=10, color=(1, 1, 1))
        page.insert_text((575, 320), "invisible", fontsize=10, render_mode=3)
        page.draw_rect(pymupdf.Rect(570, 340, 600, 360), color=None, fill=(1, 1, 1))
        gray_image(page, (570, 380, 600, 400), level=255)

    assert run(write_pdf(tmp_path / "paper.pdf", draw)) == []


def test_page_of_another_size_is_left_to_the_format_check(tmp_path):
    def draw(page, number):
        page.insert_text((570, 300), "note", fontsize=10)

    assert run(write_pdf(tmp_path / "paper.pdf", draw, size=(595, 842))) == []


def test_turned_page_names_the_side_as_a_viewer_shows_it(tmp_path):
    def draw(page, number):
        gray_image(page, (570, 300, 600, 330))

    (finding,) = run(write_pdf(tmp_path / "paper.pdf", draw, rotation=90))
    assert "into the bottom margin" in finding.message


def test_line_numbers_aligned_on_their_right_edge_in_both_side_margins_give_no_finding(tmp_path):
    def draw(page, number):
        for line in range(1, 41):
            text = str(line)
            width = pymupdf.get_text_length(text, fontsize=7)
            page.insert_text((39 - width, 80 + 15 * line), text, fontsize=7)
            page.insert_text((583 - width, 80 + 15 * line), str(line + 40), fontsize=7)

    assert run(write_pdf(tmp_path / "paper.pdf", draw)) == []


def test_blank_box_over_the_line_numbers_gives_no_finding(tmp_path):
    def draw(page, number):
        for line in range(1, 41):
            page.insert_text((30, 80 + 15 * line), str(line), fontsize=7)
        page.draw_rect(pymupdf.Rect(20, 200, 300, 400), color=None, fill=(1, 1, 1))

    assert run(write_pdf(tmp_path / "paper.pdf", draw)) == []


def test_listing_numbers_that_start_again_give_no_finding(tmp_path):
    def draw(page, number):
        for line, value in enumerate([1, 2, 3, 4, 5, 1, 2, 3]):
            page.insert_text((35, 300 + 12 * line), str(value), fontsize=6)

    assert run(write_pdf(tmp_path / "paper.pdf", draw)) == []


def test_column_of_table_numbers_in_the_margin_is_no_line_numbering(tmp_path):
    def draw(page, number):
        for line, value in enumerate([937, 500, 187, 61, 33]):
            page.insert_text((570, 300 + 12 * line), str(value), fontsize=10)

    (finding,) = run(write_pdf(tmp_path / "paper.pdf", draw))
    assert finding.evidence == "937 500 187 61 33"


def test_text_block_moved_into_the_top_margin_is_no_running_head(tmp_path):
    def draw(page, number):
        for baseline in range(40, 712, 12):
            page.insert_text((60, baseline), "Lorem ipsum dolor sit amet, consectetur adipiscing elit.", fontsize=10)
        page.insert_text((303, 755), "1", fontsize=10)

    (finding,) = run(write_pdf(tmp_path / "paper.pdf", draw))
    assert reach(finding, "top") == pytest.approx(19, abs=1.5)
    assert "bottom" not in finding.message


def running_heads(page, number):
    """Draw the running heads of an acmsmall page with the review option."""
    page.insert_text((46, 70), str(number + 1), fontsize=8)
    page.insert_text((418, 70), "Anon.", fontsize=8)
    page.insert_text((46, 110), "Body text inside the text block.", fontsize=10)


@pytest.mark.parametrize(("top", "expected"), [(73, []), (66, [18])])
def test_running_heads_that_content_comes_close_to_stay_out_of_the_reach(tmp_path, top, expected):
    def draw(page, number):
        running_heads(page, number)
        if number == 1:
            gray_image(page, (100, top, 300, 200))

    findings = run(write_pdf(tmp_path / "paper.pdf", draw, pages=3, size=(486, 720)), "fse-2027")
    assert [reach(finding, "top") for finding in findings] == pytest.approx(expected, abs=0.5)


def test_running_heads_with_a_rule_under_them_give_no_finding(tmp_path):
    def draw(page, number):
        page.insert_text((48, 30), "Ranking Flaky Test Failures", fontsize=9)
        page.draw_line((48, 34), (564, 34), width=0.4)
        page.insert_text((60, 70), "Body text inside the text block.", fontsize=10)

    assert run(write_pdf(tmp_path / "paper.pdf", draw, pages=2)) == []


def test_image_above_the_text_block_is_no_running_head(tmp_path):
    def draw(page, number):
        gray_image(page, (300, 20, 330, 40))
        page.insert_text((60, 70), "Body text inside the text block.", fontsize=10)

    (finding,) = run(write_pdf(tmp_path / "paper.pdf", draw))
    assert reach(finding, "top") == pytest.approx(32, abs=0.5)


def test_text_above_the_text_block_beyond_its_width_is_no_running_head(tmp_path):
    def draw(page, number):
        page.insert_text((570, 30), "note", fontsize=10)
        page.insert_text((60, 70), "Body text inside the text block.", fontsize=10)

    (finding,) = run(write_pdf(tmp_path / "paper.pdf", draw))
    assert "into the top margin" in finding.message
    assert "into the right margin" in finding.message


def test_running_head_whose_letters_reach_below_its_text_box_over_a_white_box_gives_no_finding(tmp_path):
    def draw(page, number):
        if number == 1:
            page.draw_rect(pymupdf.Rect(40, 31, 470, 273), color=None, fill=(1, 1, 1))
        page.insert_font(fontname="head", fontbuffer=pymupdf.Font("helv").buffer)
        page.insert_text((300, 70), "Sample pages", fontname="head", fontsize=8)
        page.insert_text((46, 110), "Body text inside the text block.", fontsize=10)

    drawn = write_pdf(tmp_path / "drawn.pdf", draw, pages=3, size=(486, 720))
    with pymupdf.open(drawn) as document:
        for xref in range(1, document.xref_length()):
            if document.xref_get_key(xref, "Type")[1] == "/FontDescriptor":
                # With these heights, as a subset without letters below the line names them, MuPDF ends the box
                # of a word at its baseline.
                document.xref_set_key(xref, "Ascent", "455")
                document.xref_set_key(xref, "Descent", "-3")
        document.save(tmp_path / "paper.pdf")
    assert run(tmp_path / "paper.pdf", "fse-2027") == []


def preprint_stamp(page, text: str = "arXiv:2701.00000v1 [cs.SE] 1 Jan 2027") -> None:
    """Draw gray text that runs up the left margin of the page, as arXiv stamps the first page of a preprint."""
    page.insert_text((38, 560), text, fontsize=20, rotate=90, color=(0.5, 0.5, 0.5))
    page.insert_text((72, 100), "Body text inside the text block.", fontsize=10)


def test_preprint_stamp_in_the_left_margin_gives_no_finding():
    assert run(FIXTURES / "ieee-preprint-stamp.pdf") == []


def test_note_in_the_margin_of_a_page_with_a_preprint_stamp_is_still_found(tmp_path):
    def draw(page, number):
        preprint_stamp(page)
        page.insert_text((570, 300), "note", fontsize=10)

    (finding,) = run(write_pdf(tmp_path / "paper.pdf", draw))
    assert finding.evidence == "note"
    assert "left" not in finding.message


def test_figure_in_the_left_margin_beside_a_preprint_stamp_is_found(tmp_path):
    def draw(page, number):
        preprint_stamp(page)
        page.draw_rect(pymupdf.Rect(22, 300, 300, 400), color=None, fill=(0.2, 0.2, 0.2))

    (finding,) = run(write_pdf(tmp_path / "paper.pdf", draw))
    assert finding.message.startswith("content (drawing) runs")
    assert reach(finding, "left") == pytest.approx(26, abs=1)


def test_note_in_the_left_margin_that_stands_apart_from_a_preprint_stamp_is_found(tmp_path):
    def draw(page, number):
        preprint_stamp(page)
        page.insert_text((6, 650), "note", fontsize=8)

    (finding,) = run(write_pdf(tmp_path / "paper.pdf", draw))
    assert finding.evidence == "note"
    assert "into the left margin" in finding.message


def test_preprint_identifier_that_runs_across_the_left_margin_is_found(tmp_path):
    def draw(page, number):
        page.insert_text((4, 650), "arXiv:2701.00000v1", fontsize=4)
        page.insert_text((72, 100), "Body text inside the text block.", fontsize=10)

    (finding,) = run(write_pdf(tmp_path / "paper.pdf", draw))
    assert finding.evidence == "arXiv:2701.00000v1"


def test_text_up_the_left_margin_without_a_preprint_identifier_is_found(tmp_path):
    def draw(page, number):
        preprint_stamp(page, "Table 9 continues with the results of each project")

    (finding,) = run(write_pdf(tmp_path / "paper.pdf", draw))
    assert "into the left margin" in finding.message


def test_profile_without_margins_gives_no_finding():
    profile = load("icse-2027")
    profile = dataclasses.replace(profile, format=dataclasses.replace(profile.format, margins=None))
    pdf = FIXTURES / "ieee-wide-table.pdf"
    assert margins.check(Paper(1, pdf), profile, pdf.parent) == []


def test_damaged_or_missing_pdf_gives_a_warning(tmp_path):
    for pdf in (PAPERS / "corrupt.pdf", tmp_path / "missing.pdf"):
        (finding,) = run(pdf)
        assert (finding.check, finding.severity, finding.page) == ("margins.error", Severity.WARNING, None)

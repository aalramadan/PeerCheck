"""Tests of the density check: the measures of each paper on the fixtures of tests/fixtures/density and on PDFs that
PyMuPDF writes, and the comparison of each paper with the other papers of a batch and with the template.
"""

from __future__ import annotations

import dataclasses
import shutil
from pathlib import Path

import pymupdf
import pytest

from peercheck.findings import Severity
from peercheck.models import Paper
from peercheck.papers import density, layout
from peercheck.papers.density import Density
from peercheck.profile import ProfileError, load

FIXTURES = Path(__file__).parent / "fixtures" / "density"
PAPERS = Path(__file__).parent / "fixtures" / "papers"
needs_banal = pytest.mark.skipif(not (shutil.which("perl") and shutil.which("pdftohtml")),
                                 reason="banal needs perl and pdftohtml")
# Thirty clean papers spread evenly over about the 5th to the 95th percentile of the characters per text page and of
# the small type of the IEEE papers in the calibration on arXiv papers.
CHARACTERS = [4750 + 55 * n for n in range(30)]
SMALL_TYPE = [0.004 + 0.0044 * n for n in range(30)]


def profile(venue: str = "icse-2027", **options):
    """Return a shipped profile whose density options are the given ones."""
    venue_profile = load(venue)
    return dataclasses.replace(venue_profile, checks={**venue_profile.checks, "density": options})


def batch(characters: list[float | None], small_type: list[float] | None = None) -> dict[int, Density]:
    """Return measures of papers 1, 2, and so on with the given characters per text page and small type, whose
    densest text page is page 3 and whose page with the most small type is page 4."""
    small_type = small_type or [0.02] * len(characters)
    return {number: Density(6, value, 3, round(share * 40000), 40000, 4)
            for number, (value, share) in enumerate(zip(characters, small_type), start=1)}


def flagged(findings: dict[int, list]) -> dict[int, list[str]]:
    """Return the codes of the findings of each paper that has any."""
    return {paper_id: [f.check for f in found] for paper_id, found in findings.items() if found}


def page_layout(types: list[str], characters: list[int], references_start: int | None = None) -> layout.Layout:
    """Return a banal layout with the given type and characters of each page."""
    return layout.Layout(total_pages=len(types), references_start=references_start, page_types=types,
                         page_characters=characters)


def all_pages(pdf: Path) -> layout.Layout:
    """Return a layout that types every page of a PDF as body, without references."""
    with pymupdf.open(pdf) as document:
        pages = document.page_count
    return page_layout(["body"] * pages, [6000] * pages)


def write_pdf(path: Path, lines: list[tuple[str, float, float, float, int]]) -> Path:
    """Write a one-page PDF with each (text, x, y, size, rotation) in Times."""
    with pymupdf.open() as document:
        page = document.new_page()
        for text, x, y, size, rotate in lines:
            page.insert_text((x, y), text, fontname="tiro", fontsize=size, rotate=rotate)
        document.save(path)
    return path


def column(lines: int, numbered: bool) -> list[tuple[str, float, float, float, int]]:
    """Return lines of body text in 10 pt and, if numbered, a line number in 6 pt beside each line."""
    text = [("Flaky tests pass and fail on the same code without a change.", 72, 80 + 12 * n, 10, 0)
            for n in range(lines)]
    numbers = [(str(n + 1), 50, 80 + 12 * n, 6, 0) for n in range(lines)] if numbered else []
    return text + numbers


def test_paper_far_above_the_batch_gets_a_warning_on_its_characters_per_text_page():
    measures = batch([*CHARACTERS, 7000])
    findings = density.check_batch(measures, profile())
    assert flagged(findings) == {31: ["density.characters"]}
    (finding,) = findings[31]
    assert (finding.severity, finding.page) == (Severity.WARNING, 3)
    assert finding.message.startswith("7,000 characters per text page on the denser half of its 6 text pages, ")
    assert "11.7% above the 95th percentile of the 30 other papers (6,265), possibly " in finding.message
    assert finding.message.endswith(", possibly less space around floats and headings or smaller type on some pages")


def test_paper_must_lie_more_than_the_margin_above_the_percentile():
    limit = 6265.25 * (1 + density.CHARACTER_MARGIN)
    assert flagged(density.check_batch(batch([*CHARACTERS, limit * 0.995]), profile())) == {}
    assert flagged(density.check_batch(batch([*CHARACTERS, limit * 1.005]), profile())) == {31: ["density.characters"]}


def test_clean_batch_gives_no_finding_and_an_entry_for_every_paper():
    findings = density.check_batch(batch(CHARACTERS, SMALL_TYPE), profile())
    assert findings == {paper_id: [] for paper_id in range(1, 31)}


def test_batch_smaller_than_thirty_papers_gives_no_finding():
    measures = batch([*CHARACTERS[:28], 9000], [*SMALL_TYPE[:28], 0.9])
    assert flagged(density.check_batch(measures, profile())) == {}


def test_min_batch_option_lowers_the_smallest_batch():
    measures = batch([*CHARACTERS[:28], 9000])
    assert flagged(density.check_batch(measures, profile(min_batch=10))) == {29: ["density.characters"]}


def test_percentile_option_sets_the_reference():
    (finding,) = density.check_batch(batch([*CHARACTERS, 7000]), profile(percentile=90))[31]
    assert "above the 90th percentile of the 30 other papers (6,186)" in finding.message


def test_paper_must_lie_far_above_the_template_as_well():
    measures = batch([*CHARACTERS, 7000])
    assert flagged(density.check_batch(measures, profile(template_characters=6700))) == {}
    (finding,) = density.check_batch(measures, profile(template_characters=6500))[31]
    assert "(6,265) and 7.7% above a full text page of the template (6,500), possibly " in finding.message


def test_paper_with_far_more_small_type_than_the_batch_gets_a_warning():
    measures = batch([6000] * 31, [*SMALL_TYPE, 0.4])
    findings = density.check_batch(measures, profile())
    assert flagged(findings) == {31: ["density.small-type"]}
    (finding,) = findings[31]
    assert (finding.severity, finding.page) == (Severity.WARNING, 4)
    assert finding.message.startswith("40.0% of the characters of the main text below 8 pt (16,000 of 40,000), ")
    assert "against 12.5% at the 95th percentile of the 30 other papers, possibly " in finding.message
    assert finding.message.endswith(", possibly captions, tables, listings, or figures set in small type")


def test_small_type_needs_a_quarter_of_the_characters():
    assert flagged(density.check_batch(batch([6000] * 31, [*SMALL_TYPE, 0.24]), profile())) == {}
    assert flagged(density.check_batch(batch([6000] * 31, [*SMALL_TYPE, 0.26]), profile())) == {
        31: ["density.small-type"]}


def test_small_type_needs_one_and_a_half_times_the_percentile_of_a_batch_with_much_small_type():
    assert flagged(density.check_batch(batch([6000] * 31, [0.2] * 30 + [0.29]), profile())) == {}
    assert flagged(density.check_batch(batch([6000] * 31, [0.2] * 30 + [0.31]), profile())) == {
        31: ["density.small-type"]}


def test_small_type_must_lie_far_above_the_template_as_well():
    measures = batch([6000] * 31, [*SMALL_TYPE, 0.4])
    assert flagged(density.check_batch(measures, profile(template_small_type=30))) == {}
    (finding,) = density.check_batch(measures, profile(template_small_type=2.5))[31]
    assert "of the 30 other papers and 2.5% in the template, possibly " in finding.message


def test_papers_without_a_measure_stay_out_of_the_batch():
    measures = {**batch([*CHARACTERS[:29], 7000]), 31: None, 32: Density(2, None, 6, 0, 0, None)}
    findings = density.check_batch(measures, profile())
    assert flagged(findings) == {30: ["density.characters"]}
    assert "of the 29 other papers" in findings[30][0].message
    assert findings[31] == findings[32] == []


@pytest.mark.parametrize("options", [{"percentile": 100}, {"percentile": "95"}, {"min_batch": 1},
                                     {"min_batch": True}, {"template_characters": "6600"},
                                     {"template_small_type": -1}])
def test_options_out_of_range_raise(options):
    with pytest.raises(ProfileError):
        density.check_batch(batch(CHARACTERS), profile(**options))


def test_measure_without_a_layout_is_none():
    assert density.measure(Paper(1, FIXTURES / "ieee-clean.pdf"), None) is None


def test_text_pages_leave_out_page_one_figure_pages_and_the_pages_from_the_references_on():
    pages = page_layout(["body", "body", "figure", "body", "body", "body", "bib"],
                        [3000, 6000, 500, 5000, 6400, 4000, 8000], references_start=6)
    measured = density.measure(Paper(1, FIXTURES / "ieee-clean.pdf"), pages)
    assert (measured.text_pages, measured.characters, measured.densest_page) == (3, (6400 + 6000) / 2, 5)


def test_characters_per_text_page_take_the_denser_half_of_the_text_pages():
    pages = page_layout(["body"] * 7, [3000, 6000, 3000, 6200, 4000, 6400, 5000])
    assert density.measure(Paper(1, FIXTURES / "ieee-clean.pdf"), pages).characters == (6400 + 6200 + 6000) / 3


def test_fewer_than_three_text_pages_give_no_characters_per_text_page():
    pages = page_layout(["body", "body", "body", "bib"], [3000, 6000, 6400, 8000], references_start=4)
    measured = density.measure(Paper(1, FIXTURES / "ieee-clean.pdf"), pages)
    assert (measured.text_pages, measured.characters) == (2, None)


def test_small_type_counts_the_characters_below_8_pt_before_the_references():
    clean = density.measure(Paper(1, FIXTURES / "ieee-clean.pdf"), all_pages(FIXTURES / "ieee-clean.pdf"))
    small = density.measure(Paper(1, FIXTURES / "ieee-small-type.pdf"), all_pages(FIXTURES / "ieee-small-type.pdf"))
    assert clean.small_type < 0.01
    assert small.small_type > 0.3
    pages = page_layout(["body"] * 6, [6000] * 6, references_start=5)
    before = density.measure(Paper(1, FIXTURES / "ieee-small-type.pdf"), pages)
    assert before.total < small.total


def test_eight_pt_type_of_the_template_is_not_small_type(tmp_path):
    pdf = write_pdf(tmp_path / "eight.pdf", [("Reference text in eight points " * 3, 72, 80 + 10 * n, 7.97, 0)
                                            for n in range(70)])
    measured = density.measure(Paper(1, pdf), all_pages(pdf))
    assert (measured.small, measured.small_type) == (0, 0.0)


def test_line_numbers_beside_the_body_text_are_not_small_type(tmp_path):
    plain = write_pdf(tmp_path / "plain.pdf", column(50, numbered=False))
    numbered = write_pdf(tmp_path / "numbered.pdf", column(50, numbered=True))
    measured = density.measure(Paper(1, numbered), all_pages(numbered))
    assert measured == density.measure(Paper(1, plain), all_pages(plain)) and measured.small == 0


def test_numbers_in_small_type_within_the_body_text_count(tmp_path):
    lines = column(50, numbered=False) + [(str(n), 200, 80 + 12 * n, 6, 0) for n in range(40)]
    pdf = write_pdf(tmp_path / "table.pdf", lines)
    assert density.measure(Paper(1, pdf), all_pages(pdf)).small > 0


def test_page_with_the_most_small_type_is_the_page_of_the_finding(tmp_path):
    with pymupdf.open() as document:
        for small_lines in (5, 30, 10):
            page = document.new_page()
            for text, x, y, size, rotate in column(50, numbered=False):
                page.insert_text((x, y), text, fontname="tiro", fontsize=size, rotate=rotate)
            for n in range(small_lines):
                page.insert_text((72, 700 + 4 * n), "Table cell text in five points", fontname="tiro", fontsize=5)
        document.save(tmp_path / "pages.pdf")
    measured = density.measure(Paper(1, tmp_path / "pages.pdf"), all_pages(tmp_path / "pages.pdf"))
    assert measured.small_type_page == 2


def test_rotated_text_such_as_the_arxiv_stamp_is_left_out(tmp_path):
    stamp = ("arXiv:2611.00001v1 [cs.SE] 5 Nov 2026", 30, 700, 6, 90)
    plain = write_pdf(tmp_path / "plain.pdf", column(50, numbered=False))
    stamped = write_pdf(tmp_path / "stamped.pdf", [*column(50, numbered=False), stamp])
    assert density.measure(Paper(1, stamped), all_pages(stamped)) == density.measure(Paper(1, plain),
                                                                                     all_pages(plain))


def test_too_few_characters_give_no_small_type(tmp_path):
    pdf = write_pdf(tmp_path / "short.pdf", column(10, numbered=False))
    assert density.measure(Paper(1, pdf), all_pages(pdf)).small_type is None


def test_unreadable_or_locked_pdf_gives_no_small_type(tmp_path):
    with pymupdf.open() as document:
        document.new_page().insert_text((72, 72), "Flaky tests pass and fail.", fontname="tiro")
        document.save(tmp_path / "locked.pdf", encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="user",
                      owner_pw="owner")
    pages = page_layout(["body"] * 4, [6000, 6000, 6100, 6200])
    for pdf in (PAPERS / "corrupt.pdf", tmp_path / "locked.pdf", tmp_path / "missing.pdf"):
        measured = density.measure(Paper(1, pdf), pages)
        assert (measured.characters, measured.small, measured.total, measured.small_type_page) == (6150, 0, 0, None)


@needs_banal
def test_clean_fixture_passes_and_squeezed_fixtures_get_warnings_in_a_batch_of_clean_papers():
    venue = load("icse-2027")
    measured = {}
    for number, name in enumerate(("ieee-clean", "ieee-dense", "ieee-small-type"), start=101):
        paper = Paper(number, FIXTURES / f"{name}.pdf")
        measured[number] = density.measure(paper, layout.inspect(paper, venue).layout)
    findings = density.check_batch({**batch(CHARACTERS, SMALL_TYPE), **measured}, venue)
    assert flagged(findings) == {102: ["density.characters"], 103: ["density.characters", "density.small-type"]}


@needs_banal
@pytest.mark.parametrize(("venue", "name"), [("icse-2027", "template-ieee"), ("fse-2027", "template-acmsmall")])
def test_template_measure_of_the_shipped_profile_comes_from_its_template_paper(venue, name):
    venue_profile = load(venue)
    paper = Paper(1, FIXTURES / f"{name}.pdf")
    measured = density.measure(paper, layout.inspect(paper, venue_profile).layout)
    assert round(measured.characters) == venue_profile.options("density")["template_characters"]

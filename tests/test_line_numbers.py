"""Tests of the line-number check on the fixtures of tests/fixtures/line-numbers, each built twice with pdflatex from the
LaTeX source beside it, on the other paper fixtures, and on small PDFs that PyMuPDF writes.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pymupdf
import pytest

from peercheck.findings import Severity
from peercheck.models import Paper
from peercheck.papers import line_numbers
from peercheck.profile import ProfileError, load

FIXTURES = Path(__file__).parent / "fixtures"
LINES = FIXTURES / "line-numbers"
NUMBERED = [
    FIXTURES / "papers" / "acm-small-review.pdf",
    FIXTURES / "margins" / "acm-review.pdf",
    LINES / "acm-sigconf-review.pdf",
    LINES / "ieee-lineno.pdf",
    LINES / "ieee-lineno-modulo.pdf",
]


def run(pdf: Path, venue: str = "icse-2027", **options) -> list:
    """Run the check on a PDF under a shipped profile with the given line_numbers options, if any."""
    profile = load(venue)
    if options:
        profile = dataclasses.replace(profile, checks={**profile.checks, "line_numbers": options})
    return line_numbers.check(Paper(1, pdf), profile, pdf.parent)


def write_pdf(path: Path, numbered: list[bool], start: int = 1, left: float = 40, lines: int = 45,
              every: int = 0) -> Path:
    """Write a PDF of text pages, each with a column of numbers that count the lines where numbered says so.

    With every, the count goes on from page to page, and only the lines whose number it divides show their number."""
    with pymupdf.open() as document:
        for index, has_numbers in enumerate(numbered):
            page = document.new_page()
            for line in range(lines):
                y = 72 + 630 // lines * line
                number = start + line + (index * lines if every else 0)
                page.insert_text((90, y), "Flaky tests pass and fail on the same code.", fontname="tiro", fontsize=10)
                if has_numbers and number % (every or 1) == 0:
                    page.insert_text((left, y + 7), str(number), fontname="tiro", fontsize=6)
        document.save(path)
    return path


def words(x: float, count: int, text: str = "", first: int = 1, width: float = 8, height: float = 6) -> list:
    """Return a column of words below each other at x, each the given text or else a number that counts up."""
    return [line_numbers.Word(x, 72 + 12 * line, x + width, 72 + 12 * line + height, text or str(first + line))
            for line in range(count)]


@pytest.mark.parametrize("pdf", NUMBERED, ids=lambda path: path.stem)
def test_review_versions_with_line_numbers_give_no_finding(pdf):
    assert run(pdf, missing="warning") == []


@pytest.mark.parametrize(("policy", "severity"), [("info", Severity.INFO), ("warning", Severity.WARNING),
                                                  ("error", Severity.ERROR)])
def test_paper_without_line_numbers_gets_the_severity_of_the_profile(policy, severity):
    (finding,) = run(FIXTURES / "fonts" / "acm-final.pdf", missing=policy)
    assert (finding.check, finding.severity, finding.page) == ("line-numbers.missing", severity, None)
    assert finding.message == "line numbers on 0 of 3 pages, expected line numbers on every page"


def test_numbered_listing_and_numbered_table_rows_are_no_line_numbers():
    (finding,) = run(LINES / "ieee-listing-table.pdf", missing="info")
    assert finding.message.startswith("line numbers on 0 of 2 pages")


def test_line_numbers_on_fewer_than_half_of_the_pages_count_as_missing(tmp_path):
    (finding,) = run(write_pdf(tmp_path / "one.pdf", [True, False, False]), missing="warning")
    assert finding.message.startswith("line numbers on 1 of 3 pages")
    assert run(write_pdf(tmp_path / "two.pdf", [True, False, True]), missing="warning") == []


def test_line_numbers_that_go_on_from_the_page_before_count(tmp_path):
    assert run(write_pdf(tmp_path / "later.pdf", [True], start=451), missing="warning") == []


def test_column_of_numbers_inside_the_text_is_no_line_numbering(tmp_path):
    (finding,) = run(write_pdf(tmp_path / "inside.pdf", [True], left=150), missing="warning")
    assert finding.message.startswith("line numbers on 0 of 1 page,")


def counts(runs: list) -> set:
    """Return the first and the last number of each run, once for a run that both of its edges show."""
    return {(int(found[0].text), int(found[-1].text)) for found in runs}


def test_numbers_in_the_gutter_that_the_lines_of_the_left_column_touch_go_on_with_the_run_of_the_margin():
    page = [*words(30, 20), *words(50, 20, "left", width=250, height=10), *words(296, 20, first=21),
            *words(320, 20, "right", width=240, height=10)]
    assert counts(line_numbers.number_runs(page)) == {(1, 40)}


def test_number_in_the_text_that_follows_the_last_line_number_is_no_part_of_the_run():
    page = [*words(30, 20), *words(50, 20, "left", width=100, height=10), *words(170, 1, first=21, height=10),
            *words(190, 20, "right", width=100, height=10)]
    assert counts(line_numbers.number_runs(page)) == {(1, 20)}


def test_numbers_over_the_start_of_the_right_column_run_into_the_count_of_the_right_margin():
    page = [*words(50, 20, "left", width=240, height=10), *words(296, 20),
            *words(300, 20, "right", width=240, height=10), *words(550, 20, first=21)]
    assert counts(line_numbers.number_runs(page)) == {(1, 40)}


def test_numbers_inside_the_lines_of_two_columns_that_count_on_from_column_to_column_are_no_run():
    page = [*words(50, 6, "left", width=250, height=10), *words(150, 6, height=10),
            *words(320, 5, "right", width=100, height=10), *words(430, 5, first=7, height=10)]
    assert counts(line_numbers.number_runs(page)) == set()


def test_numbered_listing_that_goes_on_at_the_top_of_the_next_column_is_no_line_numbering(tmp_path):
    with pymupdf.open() as document:
        page = document.new_page()
        for line in range(45):
            for x in (60, 330):
                page.insert_text((x, 72 + 14 * line), "Flaky tests pass and fail.", fontname="tiro", fontsize=10)
        for number in range(1, 25):
            x, line = (40, 32 + number) if number <= 12 else (310, number - 13)
            page.insert_text((x, 72 + 14 * line), str(number), fontname="tiro", fontsize=6)
        document.save(tmp_path / "listing.pdf")
    (finding,) = run(tmp_path / "listing.pdf", missing="warning")
    assert finding.message.startswith("line numbers on 0 of 1 page,")


def test_short_run_counts_with_the_numbers_of_the_page_before_that_it_goes_on_from():
    pages = [[*words(30, 20), *words(50, 20, "text", width=250)], [*words(30, 3, first=21), *words(50, 3, "text")],
             [*words(30, 3, first=30), *words(50, 3, "text")]]
    found = [line_numbers.line_counts(page) for page in pages]
    assert [counts(line_numbers.continued_runs(found.__getitem__, page)) for page in range(3)] == [
        {(1, 20)}, {(1, 23)}, set()]


def test_paper_with_a_number_at_every_fifth_line_of_widely_spaced_pages_gives_no_finding(tmp_path):
    assert run(write_pdf(tmp_path / "fifth.pdf", [True] * 3, lines=22, every=5), missing="warning") == []


def test_page_numbers_that_count_up_from_page_to_page_are_no_line_numbers(tmp_path):
    with pymupdf.open(write_pdf(tmp_path / "text.pdf", [False] * 3)) as document:
        for number, page in enumerate(document, start=1):
            page.insert_text((40, 760), str(number), fontname="tiro", fontsize=10)
        document.save(tmp_path / "page-numbers.pdf")
    (finding,) = run(tmp_path / "page-numbers.pdf", missing="warning")
    assert finding.message.startswith("line numbers on 0 of 3 pages")


def test_one_page_paper_names_its_page_in_the_singular():
    (finding,) = run(FIXTURES / "title" / "ieee-hyphenated.pdf", missing="info")
    assert finding.message.startswith("line numbers on 0 of 1 page,")


def test_fse_profile_notes_a_paper_without_line_numbers():
    (finding,) = run(FIXTURES / "fonts" / "acm-final.pdf", "fse-2027")
    assert (finding.check, finding.severity) == ("line-numbers.missing", Severity.INFO)
    assert run(FIXTURES / "papers" / "acm-small-review.pdf", "fse-2027") == []


def test_profile_without_the_option_gives_no_finding():
    assert run(FIXTURES / "fonts" / "acm-final.pdf") == []
    assert run(FIXTURES / "fonts" / "acm-final.pdf", missing="ignore") == []


def test_unknown_policy_raises():
    with pytest.raises(ProfileError):
        run(FIXTURES / "fonts" / "acm-final.pdf", missing="sometimes")


def test_unreadable_or_locked_pdf_gives_no_finding(tmp_path):
    bad = tmp_path / "icse2027-paper7.pdf"
    bad.write_bytes(b"not a pdf at all")
    with pymupdf.open() as document:
        document.new_page().insert_text((72, 72), "Flaky tests pass and fail.", fontname="tiro")
        document.save(tmp_path / "locked.pdf", encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="user",
                      owner_pw="owner")
    for pdf in (bad, tmp_path / "missing.pdf", FIXTURES / "papers" / "corrupt.pdf", tmp_path / "locked.pdf"):
        assert run(pdf, missing="error") == []

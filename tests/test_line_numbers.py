"""Tests of the line-number check on the fixtures of tests/fixtures/line-numbers, each built twice with pdflatex from the
LaTeX source beside it, on the other paper fixtures, and on small PDFs that PyMuPDF writes.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pymupdf
import pytest

from peercheck.checks import line_numbers
from peercheck.findings import Severity
from peercheck.models import Paper
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


def write_pdf(path: Path, numbered: list[bool], start: int = 1, left: float = 40) -> Path:
    """Write a PDF of text pages, each with a column of numbers that count the lines where numbered says so."""
    with pymupdf.open() as document:
        for has_numbers in numbered:
            page = document.new_page()
            for line in range(45):
                y = 72 + 14 * line
                page.insert_text((90, y), "Flaky tests pass and fail on the same code.", fontname="tiro", fontsize=10)
                if has_numbers:
                    page.insert_text((left, y + 7), str(start + line), fontname="tiro", fontsize=6)
        document.save(path)
    return path


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

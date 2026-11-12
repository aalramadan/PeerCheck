"""Tests of the title check on the fixtures of tests/fixtures/title, each built twice with pdflatex from the LaTeX source
beside it, on the other paper fixtures and the samples, and on small PDFs that PyMuPDF writes.
"""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path

import pymupdf
import pytest

from peercheck.findings import Severity
from peercheck.models import Paper
from peercheck.papers import title_match
from peercheck.profile import load

TESTS = Path(__file__).parent
FIXTURES = TESTS / "fixtures"
TITLE = FIXTURES / "title"
SAMPLE = "FlakeScope: Ranking Flaky Test Failures"
DETECTING = "Detecting Order-Dependent Flaky Tests in Java Projects"
MAINTENANCE = "A Study of Maintenance Effort"
RANKING = "Ranking Flaky Test Failures with Build Histories and Change Distance"
SIMILARITY = re.compile(r"\(similarity (\d+) of 100, expected (\d+) or more\)$")


def run(pdf: Path, title: str, **options) -> list:
    """Run the check on a PDF with a sheet title under the ICSE profile with the given title options."""
    profile = load("icse-2027")
    if options:
        profile = dataclasses.replace(profile, checks={**profile.checks, "title": options})
    return title_match.check(Paper(1, pdf, title), profile, pdf.parent)


def write_pdf(path: Path, *texts: tuple[str, float, float, float, int], metadata: dict | None = None) -> Path:
    """Write a one-page PDF with each (text, x, y, size, rotation) in Times, a gray box, and the given metadata."""
    with pymupdf.open() as document:
        page = document.new_page()
        page.draw_rect(pymupdf.Rect(72, 400, 300, 500), color=(0.3, 0.3, 0.3), fill=(0.8, 0.8, 0.8))
        for text, x, y, size, rotate in texts:
            page.insert_text((x, y), text, fontname="tiro", fontsize=size, rotate=rotate)
        if metadata:
            document.set_metadata(metadata)
        document.save(path)
    return path


CLEAN = [
    *[(path, SAMPLE) for path in sorted((TESTS.parent / "examples" / "papers").glob("*.pdf"))],
    *[(FIXTURES / "papers" / f"{name}.pdf", MAINTENANCE) for name in (
        "acm-small-review", "ieee-9pt-option", "ieee-linespread", "ieee-over-page-limit", "ieee-refs-start-p10",
        "ieee-three-reference-pages")],
    (FIXTURES / "papers" / "article-a4-12pt.pdf", "A Draft on Refactoring"),
    (FIXTURES / "fonts" / "ieee-conference.pdf", DETECTING),
    (FIXTURES / "fonts" / "acm-final.pdf", DETECTING),
    *[(FIXTURES / "margins" / f"{name}.pdf", RANKING) for name in ("ieee-clean", "acm-clean", "acm-review")],
    (TITLE / "ieee-hyphenated.pdf", "Profiling Workflow Failures with Build Histories"),
    (TITLE / "acm-subtitle.pdf", "FlakeScope: Ranking Flaky Test Failures with Build Histories"),
    (TITLE / "acm-subtitle.pdf", "FlakeScope"),
    (TITLE / "acm-subtitle.pdf", "Ranking Flaky Test Failures with Build Histories"),
    # The paper and the title in the author sheet that the SIGSOFT checker tests with.
    (TESTS.parent / "external" / "submission-checker" / "src" / "test" / "resources" / "icse2017-paper13.pdf",
     "A Test-suite Diagnosability Metric for Spectrum-based Fault Localization Approaches"),
]


@pytest.mark.parametrize(("pdf", "title"), CLEAN,
                         ids=lambda value: value.stem if isinstance(value, Path) else value[:24])
def test_template_papers_with_their_own_titles_give_no_finding(pdf, title):
    assert run(pdf, title) == []


def test_title_of_another_paper_is_a_warning_on_page_1():
    (finding,) = run(FIXTURES / "fonts" / "ieee-conference.pdf", MAINTENANCE)
    assert (finding.check, finding.severity, finding.page) == ("title.mismatch", Severity.WARNING, 1)
    assert finding.message.startswith("title on page 1 differs from the title in the submissions file")
    score, minimum = map(int, SIMILARITY.search(finding.message).groups())
    assert score < minimum == 70


def test_warning_names_neither_title():
    # The HTML report leaves out paper titles, since a title can identify a submission.
    (finding,) = run(TITLE / "ieee-hyphenated.pdf", DETECTING)
    for words in ("Profiling", "Workflow", "Detecting", "Order-Dependent"):
        assert words not in finding.message and words not in finding.evidence


@pytest.mark.parametrize(("sheet", "title"), [
    (DETECTING, DETECTING.upper()),
    (DETECTING, "detecting order dependent flaky tests in java projects"),
    (SAMPLE, "FlakeScope - Ranking Flaky Test Failures."),
    (SAMPLE, "\u201cFlakeScope\u201d: Ranking Flaky Test Failures"),
    ("Profiling Workflow Failures with Build Histories", "Profiling Workflow Fail-\nures with\nBuild Histories"),
    ("Profiling Workflow Failures with Build Histories", "Pro\ufb01ling Work\ufb02ow Failures with Build Histories"),
    ("Mining the Bug Reports of K\u00e4stner Tools", "Mining the Bug Reports of Kastner Tools"),
    (r"\textsc{FlakeScope}: Ranking Flaky Test Failures", SAMPLE),
    ("FlakeScope", SAMPLE),
    (SAMPLE, "Ranking Flaky Test Failures"),
    ("FlakeScope \u2014 Ranking Flaky Test Failures", "FlakeScope"),
    ("Is Flakiness Inevitable? A Study of Test Reruns", "Is Flakiness Inevitable"),
], ids=["upper-case", "lower-case", "dash-and-period", "quotes", "line-breaks", "ligatures", "accent", "latex",
        "subtitle-added", "main-title-dropped", "em-dash", "question-mark"])
def test_titles_that_differ_in_case_punctuation_line_breaks_or_a_subtitle_are_the_same(sheet, title):
    assert title_match.same_title(sheet, title)


@pytest.mark.parametrize(("sheet", "title"), [
    (DETECTING, MAINTENANCE),
    (SAMPLE, "Profiling Workflow Failures with Build Histories"),
    ("A Draft on Refactoring", DETECTING),
    ("TBD", DETECTING),
])
def test_titles_of_two_papers_score_below_the_threshold(sheet, title):
    assert not title_match.same_title(sheet, title)
    assert title_match.similarity(sheet, title) < title_match.SIMILARITY_MIN


def test_revised_title_that_keeps_most_words_gives_no_finding():
    assert run(FIXTURES / "fonts" / "ieee-conference.pdf", "Finding Order-Dependent Flaky Tests in Java Projects") == []
    assert run(FIXTURES / "fonts" / "ieee-conference.pdf", "Detecting Order-Dependent Flaky Tests in Java") == []


def test_similarity_min_of_the_profile_sets_the_threshold():
    (finding,) = run(FIXTURES / "fonts" / "ieee-conference.pdf", "Finding Order-Dependent Flaky Tests in Java Projects",
                     similarity_min=95)
    assert finding.check == "title.mismatch" and finding.message.endswith("expected 95 or more)")


def test_placeholder_sheet_title_is_a_warning():
    (finding,) = run(FIXTURES / "fonts" / "ieee-conference.pdf", "TBD")
    assert finding.check == "title.mismatch"


def test_sheet_title_in_the_first_characters_of_page_1_counts_as_found(tmp_path):
    pdf = write_pdf(tmp_path / "banner.pdf", ("UNDER REVIEW", 150, 60, 30, 0), ("Ranking Flaky Test Failures", 72, 110, 18, 0))
    assert run(pdf, "Ranking Flaky Test Failures") == []


def test_drop_cap_stamp_and_line_numbers_are_not_taken_for_the_title(tmp_path):
    numbers = [(str(number), 30, 100 + 12 * number, 6, 0) for number in range(1, 40)]
    pdf = write_pdf(tmp_path / "title.pdf", ("Flaky Rankings", 150, 80, 24, 0), ("F", 72, 300, 40, 0),
                    ("arXiv:2601.00001v1 [cs.SE] 5 Jan 2026", 20, 700, 30, 90), *numbers)
    # A title of two words never counts as found in the first characters of page 1.
    assert run(pdf, "Flaky Rankings") == []
    (finding,) = run(pdf, "Mutation Testing of Spreadsheets")
    assert finding.page == 1 and finding.message.startswith("title on page 1 differs")


def test_title_in_small_capitals_made_of_smaller_letters_is_read_whole(tmp_path):
    pieces, x = [], 150.0
    for part, size in (("T", 24), ("AKE ", 17), ("O", 24), ("VER", 17)):
        pieces.append((part, x, 80, size, 0))
        x += pymupdf.get_text_length(part, fontname="tiro", fontsize=size)
    pdf = write_pdf(tmp_path / "small-caps.pdf", *pieces)
    assert run(pdf, "Take Over") == []


def test_metadata_title_stands_in_for_a_page_without_text(tmp_path):
    pdf = write_pdf(tmp_path / "scan.pdf", metadata={"title": DETECTING})
    assert run(pdf, DETECTING) == []
    (finding,) = run(pdf, MAINTENANCE)
    assert (finding.check, finding.severity, finding.page) == ("title.mismatch", Severity.WARNING, None)
    assert finding.message.startswith("metadata title differs from the title in the submissions file")


def test_metadata_title_counts_when_the_text_of_page_1_differs(tmp_path):
    pdf = write_pdf(tmp_path / "garbled.pdf", ("Qxvz Wkpt Jrrm", 72, 80, 24, 0), metadata={"title": DETECTING})
    assert run(pdf, DETECTING) == []


def test_pdf_without_a_title_gives_an_info_note(tmp_path):
    (finding,) = run(write_pdf(tmp_path / "empty.pdf"), DETECTING)
    assert (finding.check, finding.severity, finding.page) == ("title.not-found", Severity.INFO, None)


def test_paper_without_a_sheet_title_gives_no_finding():
    assert run(FIXTURES / "fonts" / "ieee-conference.pdf", "") == []
    assert run(FIXTURES / "fonts" / "ieee-conference.pdf", "  ") == []


def test_unreadable_or_locked_pdf_gives_no_finding(tmp_path):
    bad = tmp_path / "icse2027-paper7.pdf"
    bad.write_bytes(b"not a pdf at all")
    with pymupdf.open() as document:
        document.new_page().insert_text((72, 72), DETECTING, fontname="tiro", fontsize=24)
        document.save(tmp_path / "locked.pdf", encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="user",
                      owner_pw="owner")
    for pdf in (bad, tmp_path / "missing.pdf", FIXTURES / "papers" / "corrupt.pdf", tmp_path / "locked.pdf"):
        assert run(pdf, MAINTENANCE) == []

"""Tests of the unresolved-reference check on tests/fixtures/unresolved, built by make_fixtures.py there."""

from __future__ import annotations

import shutil
from pathlib import Path

import pymupdf
import pytest

from peercheck.findings import Severity
from peercheck.models import Paper
from peercheck.papers import unresolved_references
from peercheck.profile import load

FIXTURES = Path(__file__).parent / "fixtures" / "unresolved"
INTEGRITY = Path(__file__).parent / "fixtures" / "integrity"
PAPERS = Path(__file__).parent / "fixtures" / "papers"
SAMPLES = Path(__file__).resolve().parents[1] / "examples" / "papers"
CLEAN = [FIXTURES / "ieee.pdf", INTEGRITY / "paper.pdf", *sorted(SAMPLES.glob("*.pdf")),
         *sorted(pdf for pdf in PAPERS.glob("*.pdf") if pdf.name != "corrupt.pdf")]


def run(pdf: Path) -> list:
    """Run the check on one PDF with the FSE 2027 profile."""
    return unresolved_references.check(Paper(1, pdf), load("fse-2027"), pdf.parent)


def write_pages(path: Path, *paragraphs: str) -> Path:
    """Write a PDF with one page for each paragraph of HTML, where <b> sets bold type, and return its path."""
    with pymupdf.open() as document:
        for html in paragraphs:
            document.new_page().insert_htmlbox(pymupdf.Rect(50, 50, 550, 700), f"<p>{html}</p>")
        document.save(path)
    return path


@pytest.mark.parametrize("case, count", [
    ("ieee-once", 14),
    # natbib sets an undefined \citeauthor as a lone ?, which the check leaves out.
    ("acm-once", 17),
    ("lualatex-once", 2),
    ("ieee-missing", 2),
])
def test_build_with_undefined_references_gives_one_note_with_the_count(case, count):
    (finding,) = run(FIXTURES / f"{case}.pdf")
    assert (finding.check, finding.severity) == ("unresolved.marks", Severity.INFO)
    assert finding.message == f"{count} marks of undefined references or citations, such as ?? or [?], on page 1."


def test_error_text_of_word_counts_as_a_mark_also_where_it_wraps():
    (finding,) = run(FIXTURES / "word-errors.pdf")
    assert finding.message == "3 marks of undefined references or citations, such as ?? or [?], on page 1."
    first, second = finding.evidence.split(" | ")
    assert "Fig. Error! Reference source not found. and" in first
    assert "as Error! Bookmark not defined. describes" in second


def test_other_error_message_in_the_text_gives_no_finding(tmp_path):
    pdf = write_pages(tmp_path / "log.pdf", "The log prints <b>Error! File not found.</b> Error! Reference missing.")
    assert run(pdf) == []


@pytest.mark.parametrize("pdf", CLEAN, ids=lambda pdf: pdf.name)
def test_clean_build_gives_no_finding(pdf):
    assert run(pdf) == []


def test_examples_show_the_undefined_label_and_key_with_their_page():
    (finding,) = run(FIXTURES / "ieee-missing.pdf")
    first, second = finding.evidence.split(" | ")
    assert first.startswith("page 1: ") and first.endswith("test order [?]")
    assert second == "page 1: follows in Section ??."


def test_evidence_holds_at_most_three_examples():
    (finding,) = run(FIXTURES / "ieee-once.pdf")
    examples = finding.evidence.split(" | ")
    assert len(examples) == unresolved_references.EXAMPLES
    assert all(example.startswith("page 1: ") for example in examples)


@pytest.mark.parametrize("html", [
    "A developer asked, “Why?? The test passed yesterday!” and another wrote “Really?!”",
    "The value f(?) stays open, and the most common (?) cause is the order of the tests.",
    "The pattern [?] matches a literal question mark, and ??? stands for three.",
    "A third asked, “Is this the right page??” and nobody answered.",
    "J. Doe, “Flaky tests,” in Proc. of a future venue, to appear, pp. ??–??, pages ??–??.",
    "<b>What now??</b> The tool ranks the failures. <b>Is it flaky?</b> The history decides.",
    "As <b>?</b> show, the order of the tests matters.",
    "<b>?</b>",
    "Participants (<b>P1</b>) and versions [<b>v2</b>] stay in bold.",
])
def test_question_marks_of_plain_text_are_no_marks(tmp_path, html):
    assert run(write_pages(tmp_path / "plain.pdf", html)) == []


@pytest.mark.parametrize("html, count", [
    ("As shown in <b>??</b>, the order matters.", 1),
    ("Prior work [1, <b>?</b>] and (Smith 2020; <b>?</b>) and [<b>?</b>, 3].", 3),
    ("Two citations [<b>? ?</b> ] of natbib.", 2),
    ("Answered in RQ<b>??</b> and Eq. (<b>??</b>).", 2),
    ("Plain Fig. ?? and Table ?? and Eq. (??) and RQ?? and §??.", 5),
    ("Section \u2047 describes the method.", 1),
])
def test_bold_marks_and_marks_after_a_reference_word_count(tmp_path, html, count):
    (finding,) = run(write_pages(tmp_path / "marks.pdf", html))
    noun = "mark" if count == 1 else "marks"
    assert finding.message.startswith(f"{count} {noun} of undefined references or citations")


@pytest.mark.parametrize("marked, named", [
    ([2], "page 2"),
    ([2, 4], "pages 2 and 4"),
    ([1, 3, 5], "pages 1, 3, and 5"),
    ([1, 2, 3, 5], "pages 1 to 3 and 5"),
    ([1, 2, 4, 5], "pages 1, 2, 4, and 5"),
])
def test_marked_pages_are_named_in_order_with_runs_as_ranges(tmp_path, marked, named):
    paragraphs = ["See Section <b>??</b>." if number in marked else "No mark on this page." for number in range(1, 6)]
    (finding,) = run(write_pages(tmp_path / "pages.pdf", *paragraphs))
    assert finding.message.endswith(f"on {named}.")


def test_page_that_mupdf_refuses_keeps_the_marks_of_the_other_pages(tmp_path):
    pdf = write_pages(tmp_path / "padded.pdf", "See Section <b>??</b>.")
    with pymupdf.open(pdf) as document:
        page = document.new_page()
        stream = document.get_new_xref()
        document.update_object(stream, "<<>>")
        document.update_stream(stream, b"q " * 100000 + b"Q " * 100000)
        page.set_contents(stream)
        document.save(tmp_path / "refused.pdf")
    (finding,) = run(tmp_path / "refused.pdf")
    assert finding.message.endswith("on page 1.")


@pytest.mark.parametrize("pdf", [INTEGRITY / "user-password.pdf", INTEGRITY / "cut.pdf", PAPERS / "corrupt.pdf"],
                         ids=lambda pdf: pdf.name)
def test_pdf_that_does_not_open_gives_no_finding(pdf):
    assert run(pdf) == []


def test_missing_file_gives_no_finding(tmp_path):
    assert run(tmp_path / "missing.pdf") == []


def test_finding_names_no_file_or_path(tmp_path):
    copy = tmp_path / "fse2027-paper42.pdf"
    shutil.copyfile(FIXTURES / "ieee-once.pdf", copy)
    (finding,) = run(copy)
    for text in (finding.message, finding.evidence):
        assert str(tmp_path) not in text and copy.name not in text

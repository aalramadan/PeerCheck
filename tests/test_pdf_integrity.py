"""Tests of the PDF integrity check on the fixtures of tests/fixtures/integrity, built by make_fixtures.py there."""

from __future__ import annotations

import shutil
from pathlib import Path

import pikepdf
import pytest

from peercheck.findings import Severity
from peercheck.models import Paper
from peercheck.papers import pdf_integrity
from peercheck.profile import load

FIXTURES = Path(__file__).parent / "fixtures" / "integrity"
PAPERS = Path(__file__).parent / "fixtures" / "papers"
SAMPLES = Path(__file__).resolve().parents[1] / "examples" / "papers"
CLEAN = [FIXTURES / "paper.pdf", *sorted(SAMPLES.glob("*.pdf")),
         *sorted(pdf for pdf in PAPERS.glob("*.pdf") if pdf.name != "corrupt.pdf")]


def run(pdf: Path) -> list:
    """Run the check on one PDF with the FSE 2027 profile."""
    return pdf_integrity.check(Paper(1, pdf), load("fse-2027"), pdf.parent)


def codes(findings: list) -> list[tuple[str, Severity]]:
    """Return the check and the severity of each finding."""
    return [(f.check, f.severity) for f in findings]


def encrypted_copy(tmp_path: Path, **denied: bool) -> Path:
    """Save the clean paper with an owner password, no password to open, and the given permissions turned off."""
    target = tmp_path / "encrypted.pdf"
    with pikepdf.open(FIXTURES / "paper.pdf") as pdf:
        pdf.save(target, encryption=pikepdf.Encryption(owner="author", user="", allow=pikepdf.Permissions(**denied)))
    return target


@pytest.mark.parametrize("pdf", CLEAN, ids=lambda pdf: pdf.name)
def test_clean_pdf_gives_no_finding(pdf):
    assert run(pdf) == []


def test_password_to_open_is_the_only_finding_and_an_error():
    assert codes(run(FIXTURES / "user-password.pdf")) == [("pdf.password", Severity.ERROR)]


def test_owner_password_that_forbids_printing_and_copying_is_a_warning():
    (finding,) = run(FIXTURES / "owner-password.pdf")
    assert (finding.check, finding.severity) == ("pdf.permissions", Severity.WARNING)
    assert finding.message == "An owner password of the PDF forbids printing and copying text."


def test_owner_password_that_forbids_comments_is_a_warning(tmp_path):
    (finding,) = run(encrypted_copy(tmp_path, modify_annotation=False))
    assert (finding.check, finding.severity) == ("pdf.permissions", Severity.WARNING)
    assert finding.message == "An owner password of the PDF forbids adding comments."


def test_owner_password_that_forbids_only_editing_is_info(tmp_path):
    (finding,) = run(encrypted_copy(tmp_path, modify_other=False))
    assert (finding.check, finding.severity) == ("pdf.encrypted", Severity.INFO)
    assert finding.message == "The PDF is encrypted but opens without a password and forbids editing."


def test_encryption_without_restrictions_is_info(tmp_path):
    assert [(f.check, f.severity, f.message) for f in run(encrypted_copy(tmp_path))] == [
        ("pdf.encrypted", Severity.INFO, "The PDF is encrypted but opens without a password.")]


def test_cut_pdf_without_a_readable_page_is_an_error():
    (finding,) = run(FIXTURES / "cut.pdf")
    assert (finding.check, finding.severity) == ("pdf.unreadable", Severity.ERROR)
    assert finding.message == "The PDF opens without a readable page."


def test_file_that_is_no_pdf_is_an_error():
    assert codes(run(PAPERS / "corrupt.pdf")) == [("pdf.unreadable", Severity.ERROR)]


def test_empty_file_is_an_error(tmp_path):
    empty = tmp_path / "empty.pdf"
    empty.write_bytes(b"")
    assert [(f.check, f.message) for f in run(empty)] == [("pdf.unreadable", "The PDF file is empty.")]


def test_missing_file_is_an_error(tmp_path):
    (finding,) = run(tmp_path / "missing.pdf")
    assert (finding.check, finding.severity) == ("pdf.unreadable", Severity.ERROR)


def test_misplaced_cross_reference_table_is_info_with_the_problems_of_qpdf():
    (finding,) = run(FIXTURES / "broken-xref.pdf")
    assert (finding.check, finding.severity) == ("pdf.damaged", Severity.INFO)
    assert finding.message == ("The PDF structure is damaged: MuPDF had to repair it on opening and qpdf reports "
                               "3 problems.")
    assert finding.evidence == "file is damaged | xref not found | Attempting to reconstruct cross-reference table"


def test_duplicated_key_that_needs_no_repair_is_info():
    (finding,) = run(FIXTURES / "duplicate-key.pdf")
    assert (finding.check, finding.severity) == ("pdf.damaged", Severity.INFO)
    assert finding.message == "The PDF structure is damaged: qpdf reports 1 problem."
    assert finding.evidence.startswith("dictionary has duplicated key /Title")


def test_file_that_qpdf_cannot_open_and_mupdf_repairs_is_info(tmp_path):
    data = (FIXTURES / "paper.pdf").read_bytes()
    pdf = tmp_path / "no-trailer.pdf"
    pdf.write_bytes(data[: data.rindex(b"startxref")])
    (finding,) = run(pdf)
    assert (finding.check, finding.severity) == ("pdf.damaged", Severity.INFO)
    assert finding.evidence == "unable to find trailer dictionary while recovering damaged file"


def test_repair_without_problems_of_qpdf_is_info(monkeypatch):
    monkeypatch.setattr(pdf_integrity, "_syntax_problems", lambda data: [])
    (finding,) = run(FIXTURES / "broken-xref.pdf")
    assert finding.message == "The PDF structure is damaged: MuPDF had to repair it on opening."


@pytest.mark.parametrize("pdf", [*sorted(FIXTURES.glob("*.pdf")), PAPERS / "corrupt.pdf"], ids=lambda pdf: pdf.name)
def test_findings_name_no_file_or_path(pdf, tmp_path):
    copy = tmp_path / "fse2027-paper42.pdf"
    shutil.copyfile(pdf, copy)
    for finding in run(copy):
        for text in (finding.message, finding.evidence):
            assert str(tmp_path) not in text and copy.name not in text and "BytesIO" not in text

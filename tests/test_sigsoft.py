"""Tests of the runner of the SIGSOFT submission checker: its command, its JSON records, and its failures."""

import shutil
from pathlib import Path

import pytest

from peercheck import profile, tools
from peercheck.checks import sigsoft
from peercheck.findings import Severity
from peercheck.models import Paper, Person

PAPERS = Path(__file__).parent / "fixtures" / "papers"


def _papers():
    author = Person("Maria", "Lindqvist", "maria.lindqvist@kth.se", "KTH")
    return [Paper(1, PAPERS / "ieee-refs-start-p10.pdf", "A", (author,)), Paper(2, PAPERS / "corrupt.pdf")]


def test_records_become_findings_with_mapped_severities():
    record = {"file": "x.pdf", "issues": [
        {"code": "author-revealing-email", "detail": "a@b.se", "page": 1},
        {"code": "paper-very-short", "detail": "5", "page": None},
        {"code": "non-references-after-p10", "detail": "Appendix", "page": 11},
        {"code": "brand-new-code", "detail": "", "page": None}]}
    found = {f.check: f.severity for f in sigsoft.findings(record)}
    assert found == {"sigsoft.author-revealing-email": Severity.ERROR, "sigsoft.paper-very-short": Severity.INFO,
                     "sigsoft.non-references-after-limit": Severity.WARNING,
                     "sigsoft.brand-new-code": Severity.WARNING}


def test_a_pdf_the_checker_cannot_open_is_a_warning_not_a_pass():
    found = sigsoft.findings({"file": "x.pdf", "error": "Missing root object", "issues": []})
    assert [(f.check, f.severity) for f in found] == [("sigsoft.error", Severity.WARNING)]


def test_command_passes_the_profile_and_the_author_list(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "program", lambda name: name)
    command = sigsoft._command(_papers(), profile.load("conf-2026"), tmp_path)
    assert command[command.index("--id-pattern") + 1] == r"_paper_(\d+)\.pdf$"
    assert "--flag-acknowledgments" in command
    assert (tmp_path / "sigsoft-authors.csv").read_text().splitlines()[1].startswith("1,A,Maria,Lindqvist")


def test_papers_without_a_record_get_a_warning(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "program", lambda name: name)
    monkeypatch.setattr(sigsoft, "_run", lambda command, n: [{"file": "ieee-refs-start-p10.pdf", "issues": []}])
    results = sigsoft.check_batch(_papers(), profile.load("conf-2026"), tmp_path)
    assert results[1] == []
    assert [f.check for f in results[2]] == ["sigsoft.error"]


@pytest.mark.skipif(not shutil.which("java") or not tools.submission_checker().is_file(),
                    reason="needs Java and the bundled jar")
def test_bundled_jar_reads_a_good_pdf_and_reports_a_corrupt_one(tmp_path):
    results = sigsoft.check_batch(_papers(), profile.load("conf-2026"), tmp_path)
    assert not [f for f in results[1] if f.check == "sigsoft.error"]
    assert [f.check for f in results[2]] == ["sigsoft.error"]


def test_issues_of_a_pdf_that_opened_survive_a_partial_failure():
    record = {"file": "x.pdf", "pages": 12, "error": "page 7 failed",
              "issues": [{"code": "author-revealing-email", "detail": "a@b.se", "page": 1}]}
    assert [f.check for f in sigsoft.findings(record)] == ["sigsoft.error", "sigsoft.author-revealing-email"]


def test_third_person_self_citations_are_info():
    record = {"file": "x.pdf", "issues": [{"code": "identity-data-in-references", "detail": "Lindqvist", "page": 11}]}
    assert sigsoft.findings(record)[0].severity is Severity.INFO

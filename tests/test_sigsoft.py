"""Tests of the runner of the SIGSOFT submission checker: its command, its JSON records, and its failures."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from peercheck import profile, tools
from peercheck.findings import Severity
from peercheck.models import Paper, Person
from peercheck.papers import sigsoft

PAPERS = Path(__file__).parent / "fixtures" / "papers"
needs_jar = pytest.mark.skipif(not shutil.which("java") or not tools.submission_checker().is_file(),
                               reason="needs Java and the bundled jar")


def _papers():
    author = Person("Maria", "Lindqvist", "maria.lindqvist@kth.se", "KTH")
    return [Paper(1, PAPERS / "ieee-refs-start-p10.pdf", "A", (author,)), Paper(2, PAPERS / "corrupt.pdf")]


class FakeJar:
    """Answers like the jar, one JSON line per PDF in the order of the arguments, until the PDF that stops it."""

    def __init__(self, stopper: str = "", timeout: bool = False, rejects: bool = False):
        self.stopper = stopper
        self.timeout = timeout
        self.rejects = rejects
        self.runs: list[tuple[list[str], float]] = []

    def __call__(self, command, **kwargs):
        pdfs = [arg for arg in command if arg.endswith(".pdf")]
        self.runs.append(([Path(pdf).name for pdf in pdfs], kwargs["timeout"]))
        lines = []
        for pdf in pdfs:
            if Path(pdf).name == self.stopper:
                output = "".join(lines)
                if self.timeout:
                    raise subprocess.TimeoutExpired(command, kwargs["timeout"], output=output.encode())
                if self.rejects:
                    return subprocess.CompletedProcess(command, 2, "", f"ERROR: Argument not a file or folder: {pdf}\n")
                stderr = 'Exception in thread "main" java.lang.OutOfMemoryError: Java heap space\n\tat Foo.bar\n'
                return subprocess.CompletedProcess(command, 1, output, stderr)
            lines.append(json.dumps({"file": pdf, "issues": []}) + "\n")
        return subprocess.CompletedProcess(command, 0, "".join(lines), "")


def _batch(tmp_path, monkeypatch, jar, count=3):
    monkeypatch.setattr(tools, "program", lambda name: name)
    monkeypatch.setattr(sigsoft.subprocess, "run", jar)
    papers = [Paper(n, tmp_path / f"conf_2026_paper_{n}.pdf") for n in range(1, count + 1)]
    return sigsoft.check_batch(papers, profile.load("icse-2027"), tmp_path)


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
    command = sigsoft._command(_papers(), profile.load("icse-2027"), tmp_path)
    assert f"--id-pattern={sigsoft.LINK_PATTERN}" in command
    assert "--flag-acknowledgments" in command
    assert (tmp_path / "sigsoft-authors.csv").read_text().splitlines()[1].startswith("1,A,Maria,Lindqvist")


def test_papers_without_a_record_get_a_warning(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "program", lambda name: name)
    monkeypatch.setattr(sigsoft, "_run",
                        lambda command, papers, timeout: ([{"file": "paper1.pdf", "issues": []}], ""))
    results = sigsoft.check_batch(_papers(), profile.load("icse-2027"), tmp_path)
    assert results[1] == []
    assert [f.check for f in results[2]] == ["sigsoft.error"]


@needs_jar
def test_bundled_jar_reads_a_good_pdf_and_reports_a_corrupt_one(tmp_path):
    results = sigsoft.check_batch(_papers(), profile.load("icse-2027"), tmp_path)
    assert not [f for f in results[1] if f.check == "sigsoft.error"]
    assert [f.check for f in results[2]] == ["sigsoft.error"]


@needs_jar
def test_bundled_jar_reads_a_paper_named_as_hotcrp_names_its_downloads(tmp_path):
    pdf = tmp_path / "conf2027-paper1.pdf"
    pdf.write_bytes((PAPERS / "ieee-refs-start-p10.pdf").read_bytes())
    results = sigsoft.check_batch([Paper(1, pdf)], profile.load("icse-2027"), tmp_path)
    assert not [f for f in results[1] if f.check == "sigsoft.error"]


def test_issues_of_a_pdf_that_opened_survive_a_partial_failure():
    record = {"file": "x.pdf", "pages": 12, "error": "page 7 failed",
              "issues": [{"code": "author-revealing-email", "detail": "a@b.se", "page": 1}]}
    assert [f.check for f in sigsoft.findings(record)] == ["sigsoft.error", "sigsoft.author-revealing-email"]


def test_third_person_self_citations_are_info():
    record = {"file": "x.pdf", "issues": [{"code": "identity-data-in-references", "detail": "Lindqvist", "page": 11}]}
    assert sigsoft.findings(record)[0].severity is Severity.INFO


def test_batch_without_a_failure_runs_the_checker_once(tmp_path, monkeypatch):
    jar = FakeJar()
    results = _batch(tmp_path, monkeypatch, jar)
    assert results == {1: [], 2: [], 3: []}
    assert len(jar.runs) == 1


def test_papers_after_a_pdf_that_stops_the_checker_run_again_alone(tmp_path, monkeypatch):
    jar = FakeJar(stopper="paper2.pdf")
    results = _batch(tmp_path, monkeypatch, jar)
    assert results[1] == results[3] == []
    assert [f.message for f in results[2]] == ["no result from the SIGSOFT checker: it ran out of memory"]
    limit = sigsoft.SECONDS_PER_PAPER
    assert jar.runs[1:] == [(["paper2.pdf"], limit), (["paper3.pdf"], limit)]


def test_timeout_keeps_the_records_that_finished_and_gives_a_short_reason(tmp_path, monkeypatch):
    results = _batch(tmp_path, monkeypatch, FakeJar(stopper="paper2.pdf", timeout=True), count=2)
    assert results[1] == []
    assert [f.message for f in results[2]] == [
        f"no result from the SIGSOFT checker: it did not finish within {sigsoft.SECONDS_PER_PAPER} seconds"]


@needs_jar
def test_bundled_jar_reads_a_paper_whose_file_name_is_no_utf8(tmp_path):
    good = tmp_path / "icse2027-paper1.pdf"
    good.write_bytes((PAPERS / "ieee-refs-start-p10.pdf").read_bytes())
    odd = os.path.join(os.fsencode(tmp_path), b"caf\xe9-icse2027-paper2.pdf")
    try:
        with open(odd, "wb") as handle:
            handle.write(good.read_bytes())
    except OSError:
        pytest.skip("the file system takes only UTF-8 file names")
    papers = [Paper(1, good), Paper(2, Path(os.fsdecode(odd)))]
    results = sigsoft.check_batch(papers, profile.load("icse-2027"), tmp_path / "work")
    assert not [f for f in results[1] + results[2] if f.check == "sigsoft.error"]


@needs_jar
def test_bundled_jar_reads_a_pdf_whose_name_starts_with_a_dash(tmp_path, monkeypatch):
    (tmp_path / "-paper1.pdf").write_bytes((PAPERS / "ieee-refs-start-p10.pdf").read_bytes())
    monkeypatch.chdir(tmp_path)
    results = sigsoft.check_batch([Paper(1, Path("-paper1.pdf"))], profile.load("icse-2027"), tmp_path / "work")
    assert not [f for f in results[1] if f.check == "sigsoft.error"]


def test_one_allowed_host_given_as_a_string_reaches_the_checker_whole(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "program", lambda name: name)
    data = yaml.safe_load((profile.PROFILES / "icse-2027.yaml").read_text())
    data["checks"]["anonymity"]["allowed_hosts"] = "zenodo.org"
    (tmp_path / "venue.yaml").write_text(yaml.safe_dump(data))
    command = sigsoft._command([], profile.load(str(tmp_path / "venue.yaml")), tmp_path)
    assert command[command.index("--allowed-hosts") + 1] == "zenodo.org"


def test_errors_of_the_checker_name_no_path_or_file(tmp_path, monkeypatch):
    results = _batch(tmp_path, monkeypatch, FakeJar(stopper="paper2.pdf", rejects=True), count=2)
    assert [f.message for f in results[2]] == ["no result from the SIGSOFT checker: it rejected its arguments"]
    pdf = tmp_path / "conf_2026_paper_3.pdf"
    record = {"file": str(pdf), "error": f"FileNotFoundException: {pdf} (No such file or directory)"}
    (finding,) = sigsoft.findings(record)
    assert str(tmp_path) not in finding.message and pdf.name not in finding.message

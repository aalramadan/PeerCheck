"""Tests of the reference check, which replay recorded output of Hallucinator 0.2.4 in place of the binary.

The fixtures come from real runs. offline-run.json is the offline run on sample-paper.pdf, built from
sample-paper.tex, with ten real references and three fabricated ones. online-run.json and arxiv-run.json are
the two runs of the online mode on online-sample.tex, and arxiv-lookups.bib is the file of its second run.
broken-pdf.stderr is the error output on a file that is no PDF.
"""

from __future__ import annotations

import dataclasses
import gzip
import hashlib
import io
import json
import os
import subprocess
import tarfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar

import pytest

from peercheck import profile as profile_module
from peercheck import retraction_watch, tools
from peercheck.checks import references
from peercheck.findings import Severity
from peercheck.models import Paper

FIXTURES = Path(__file__).parent / "fixtures" / "references"


class FakeHallucinator:
    """Replays reports, each a fixture name or loaded JSON, one per run, and keeps each command and environment."""

    def __init__(self, *reports, returncode: int = 0, stderr: str = ""):
        self.reports = list(reports)
        self.returncode = returncode
        self.stderr = stderr
        self.calls: list[tuple[list[str], dict]] = []

    def __call__(self, command, **kwargs):
        self.calls.append((list(command), kwargs))
        report = self.reports.pop(0) if self.reports else None
        if report:
            text = (FIXTURES / report).read_text(encoding="utf-8") if isinstance(report, str) else json.dumps(report)
            Path(command[command.index("--json") + 1]).write_text(text, encoding="utf-8")
        return subprocess.CompletedProcess(command, self.returncode, "", self.stderr)

    def disabled(self, call: int = 0) -> list[str]:
        command = self.calls[call][0]
        return command[command.index("--disable-dbs") + 1].split(",") if "--disable-dbs" in command else []


@pytest.fixture
def cache(tmp_path):
    """A cache with a stand-in binary, a stand-in DBLP database, and the tiny Retraction Watch CSV."""
    folder = tmp_path / "cache" / "hallucinator"
    (folder / references.VERSION).mkdir(parents=True)
    (folder / references.VERSION / "hallucinator-cli").write_text("", encoding="utf-8")
    (folder / "dblp.db").write_text("", encoding="utf-8")
    (tmp_path / "cache" / "retraction_watch.csv").write_bytes((FIXTURES / "retraction_watch.csv").read_bytes())
    return tmp_path / "cache"


def run(tmp_path, cache, fake, monkeypatch, **options):
    monkeypatch.setattr(references.subprocess, "run", fake)
    monkeypatch.setattr(references.platform, "system", lambda: "Linux")
    profile = profile_module.load("icse-2027")
    profile = dataclasses.replace(profile, checks={**profile.checks, "references": {"cache": str(cache), **options}})
    return references.check(Paper(paper_id=7, pdf=tmp_path / "paper.pdf"), profile, tmp_path / "work")


def by_check(findings, check):
    return [f for f in findings if f.check == check]


def test_offline_run_reports_fabricated_references_as_not_found(tmp_path, cache, monkeypatch):
    findings = run(tmp_path, cache, FakeHallucinator("offline-run.json"), monkeypatch)
    missing = by_check(findings, "references.not-found")
    assert [f.message.split('"')[0] for f in missing] == ["Reference [11] ", "Reference [13] "]
    assert all(f.severity is Severity.WARNING and f.message.endswith("was not found in DBLP") for f in missing)


def test_offline_run_reports_a_real_title_with_false_authors_as_author_mismatch(tmp_path, cache, monkeypatch):
    findings = run(tmp_path, cache, FakeHallucinator("offline-run.json"), monkeypatch)
    [mismatch] = by_check(findings, "references.author-mismatch")
    assert mismatch.message.startswith('Reference [12] "Automatically finding patches using genetic programming"')
    assert "Claire Le Goues" in mismatch.message
    assert mismatch.evidence.startswith("T. Brennan, K. Ito, and S. Malhotra")


def test_offline_run_reports_a_cited_work_with_a_retraction_notice(tmp_path, cache, monkeypatch):
    findings = run(tmp_path, cache, FakeHallucinator("offline-run.json"), monkeypatch)
    [retracted] = by_check(findings, "references.retracted")
    assert retracted.severity is Severity.WARNING
    assert retracted.message.startswith("Reference [10] ")
    assert retracted.message.endswith("Retraction of 2008-04-03")
    assert retracted.evidence == "DOI 10.1109/aswec.2008.4483193. Reason: Euphemisms for Plagiarism"


def test_evidence_holds_at_most_200_characters_of_the_reference_text(tmp_path, cache, monkeypatch):
    findings = run(tmp_path, cache, FakeHallucinator("offline-run.json"), monkeypatch)
    [first, *_] = by_check(findings, "references.not-found")
    assert len(first.evidence) <= 200
    assert first.evidence.startswith("M. Hartmann, P. Venkataraman, and L. Oberg")
    assert first.evidence.endswith("...")


def test_summary_counts_the_references_of_the_run(tmp_path, cache, monkeypatch):
    findings = run(tmp_path, cache, FakeHallucinator("offline-run.json"), monkeypatch)
    [summary] = by_check(findings, "references.summary")
    assert summary.severity is Severity.INFO
    assert summary.message == ("Hallucinator checked 13 references offline against DBLP: 10 found, 2 not found, "
                               "1 with other authors or identifiers, 0 skipped")


def test_default_run_disables_every_online_source_and_uses_the_local_dblp(tmp_path, cache, monkeypatch):
    fake = FakeHallucinator("offline-run.json")
    run(tmp_path, cache, fake, monkeypatch)
    command = fake.calls[0][0]
    assert set(fake.disabled()) == set(references.ONLINE_SOURCES) - {"DBLP"}
    assert command[command.index("--dblp-offline") + 1] == str(cache / "hallucinator" / "dblp.db")
    assert "--no-searxng" in command and "--url-match" not in command
    assert command[command.index("--config") + 1].endswith("hallucinator.toml")
    assert len(fake.calls) == 1


def test_offline_run_hides_keys_and_proxies_of_the_user(tmp_path, cache, monkeypatch):
    monkeypatch.setenv("OPENALEX_KEY", "not-a-real-key")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:3128")
    fake = FakeHallucinator("offline-run.json")
    run(tmp_path, cache, fake, monkeypatch)
    env = fake.calls[0][1]["env"]
    assert "OPENALEX_KEY" not in env and "HTTPS_PROXY" not in env
    assert env["HOME"] == str(tmp_path / "work" / "references")


def test_online_option_allows_doi_lookups_only_in_the_first_run(tmp_path, cache, monkeypatch):
    fake = FakeHallucinator("online-run.json", "arxiv-run.json")
    run(tmp_path, cache, fake, monkeypatch, online=True)
    assert set(references.ONLINE_SOURCES) - set(fake.disabled(0)) == {"DBLP", "DOI"}


def test_online_option_looks_up_arxiv_ids_through_the_arxiv_source_alone(tmp_path, cache, monkeypatch):
    fake = FakeHallucinator("online-run.json", "arxiv-run.json")
    run(tmp_path, cache, fake, monkeypatch, online=True)
    command = fake.calls[1][0]
    assert set(references.ONLINE_SOURCES) - set(fake.disabled(1)) == {"arXiv"}
    assert "--dblp-offline" not in command
    bib = Path(command[-1])
    assert bib.read_text(encoding="utf-8") == (FIXTURES / "arxiv-lookups.bib").read_text(encoding="utf-8")


def test_online_option_merges_the_arxiv_answers_into_the_findings(tmp_path, cache, monkeypatch):
    findings = run(tmp_path, cache, FakeHallucinator("online-run.json", "arxiv-run.json"), monkeypatch, online=True)
    [mismatch] = by_check(findings, "references.author-mismatch")
    assert mismatch.message.startswith("Reference [2] ")
    assert mismatch.message.endswith("matches a title in arXiv whose authors differ: The ATLAS Collaboration")
    [missing] = by_check(findings, "references.not-found")
    assert missing.message.startswith("Reference [3] ") and missing.message.endswith("was not found in DBLP, arXiv")
    assert by_check(findings, "references.summary")[0].message.startswith(
        "Hallucinator checked 3 references with DOI and arXiv ID lookups against DBLP: 1 found, 1 not found")


def test_online_titles_option_allows_every_title_source(tmp_path, cache, monkeypatch):
    monkeypatch.setenv("CROSSREF_MAILTO", "chair@example.org")
    fake = FakeHallucinator("online-run.json")
    run(tmp_path, cache, fake, monkeypatch, online_titles=True)
    assert fake.disabled() == []
    assert fake.calls[0][1]["env"]["CROSSREF_MAILTO"] == "chair@example.org"
    assert len(fake.calls) == 1


def test_offline_arxiv_database_replaces_the_online_arxiv_source(tmp_path, cache, monkeypatch):
    arxiv_db = tmp_path / "arxiv.db"
    arxiv_db.write_text("", encoding="utf-8")
    fake = FakeHallucinator("offline-run.json")
    run(tmp_path, cache, fake, monkeypatch, arxiv_db=str(arxiv_db))
    command = fake.calls[0][0]
    assert command[command.index("--arxiv-offline") + 1] == str(arxiv_db)
    assert "arXiv" not in fake.disabled()


def test_identifier_that_resolves_to_another_work_is_reported(tmp_path, cache, monkeypatch):
    report = json.loads((FIXTURES / "offline-run.json").read_text(encoding="utf-8"))
    entry = next(r for r in report[0]["references"] if r["original_number"] == 1)
    entry.update(status="mismatch", doi_info={"doi": "10.1145/3180155.3180167", "valid": False, "title": None})
    findings = run(tmp_path, cache, FakeHallucinator(report), monkeypatch, online_titles=True)
    [wrong] = by_check(findings, "references.identifier-mismatch")
    assert wrong.message == 'Reference [1] "Deep code search" gives a DOI that does not resolve to this work'
    assert not [f for f in by_check(findings, "references.author-mismatch") if "[1]" in f.message]


def test_parse_report_finds_dois_in_the_reference_text():
    entry = {"original_number": 4, "title": "T", "status": "verified",
             "raw_citation": "A. B, “T,” 2020, doi: 10.1000/abc(1)), see https://doi.org/10.2000/X.Y."}
    [ref] = references.parse_report([{"references": [entry]}])
    assert ref.dois == ("10.1000/abc(1)", "10.2000/X.Y")


@pytest.mark.parametrize("wrapped", ["10.1109/ ASWEC.2008.4483193", "10.1109/ASWEC.2008. 4483193"])
def test_doi_cut_by_a_line_break_still_finds_the_retraction_notice(tmp_path, cache, monkeypatch, wrapped):
    # Hallucinator turns the line break inside a wrapped DOI into a space.
    report = json.loads((FIXTURES / "offline-run.json").read_text(encoding="utf-8"))
    entry = next(r for r in report[0]["references"] if r["original_number"] == 10)
    entry["raw_citation"] = entry["raw_citation"].replace("10.1109/ASWEC.2008.4483193", wrapped)
    findings = run(tmp_path, cache, FakeHallucinator(report), monkeypatch)
    [retracted] = by_check(findings, "references.retracted")
    assert retracted.evidence.startswith("DOI 10.1109/aswec.2008.4483193.")


def test_doi_followed_by_a_year_is_read_without_the_year():
    assert "10.1145/3377811.3380362" in references._dois("ICSE, 2020, doi: 10.1145/3377811.3380362. 2020.")


def test_parse_report_finds_arxiv_ids_in_the_reference_text():
    entry = {"original_number": 1, "title": "T", "status": "not_found", "raw_citation": "arXiv preprint arXiv: 2401.01234v2"}
    assert references.parse_report([{"references": [entry]}])[0].arxiv_id == "2401.01234v2"


def test_missing_binary_is_reported_as_an_error(tmp_path, cache, monkeypatch):
    (cache / "hallucinator" / references.VERSION / "hallucinator-cli").unlink()
    [error] = run(tmp_path, cache, FakeHallucinator("offline-run.json"), monkeypatch)
    assert error.check == "references.error" and error.severity is Severity.WARNING
    assert "Hallucinator is not installed" in error.message and "peercheck setup references" in error.message


def test_missing_dblp_database_is_reported_as_an_error(tmp_path, cache, monkeypatch):
    (cache / "hallucinator" / "dblp.db").unlink()
    [error] = run(tmp_path, cache, FakeHallucinator("offline-run.json"), monkeypatch)
    assert error.check == "references.error" and "offline DBLP database is missing" in error.message


def test_broken_pdf_is_reported_with_the_message_of_the_tool(tmp_path, cache, monkeypatch):
    stderr = (FIXTURES / "broken-pdf.stderr").read_text(encoding="utf-8")
    [error] = run(tmp_path, cache, FakeHallucinator(returncode=1, stderr=stderr), monkeypatch)
    assert error.check == "references.error"
    assert error.message.endswith("Error: PDF extraction error: backend error: failed to open PDF: MuPDF error, "
                                  "code: 7, message: no objects found")


def test_run_that_exceeds_the_timeout_is_reported_as_an_error(tmp_path, cache, monkeypatch):
    def slow(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    [error] = run(tmp_path, cache, slow, monkeypatch, timeout=5)
    assert error.check == "references.error" and "within 5 seconds" in error.message


def test_pdf_without_references_is_reported_as_an_error(tmp_path, cache, monkeypatch):
    [error] = run(tmp_path, cache, FakeHallucinator(), monkeypatch)
    assert (error.check, error.message) == ("references.error", "Hallucinator found no references in the PDF")


def test_missing_retraction_data_is_reported_beside_the_lookup_findings(tmp_path, cache, monkeypatch):
    (cache / "retraction_watch.csv").unlink()
    findings = run(tmp_path, cache, FakeHallucinator("offline-run.json"), monkeypatch)
    [error] = by_check(findings, "references.error")
    assert "Retraction Watch data is missing" in error.message
    assert len(by_check(findings, "references.not-found")) == 2


def test_cache_defaults_to_the_peercheck_cache_folder(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.setattr(references.platform, "system", lambda: "Linux")
    settings = references.settings_from({})
    assert settings.binary == tmp_path / "peercheck" / "hallucinator" / references.VERSION / "hallucinator-cli"
    assert settings.offline == {"DBLP": tmp_path / "peercheck" / "hallucinator" / "dblp.db"}
    assert settings.retraction_csv == tmp_path / "peercheck" / "retraction_watch.csv"


DUMP = (b'<?xml version="1.0" encoding="ISO-8859-1"?>\n<dblp>\n<article key="x"><author>Ren&eacute; Just</author>'
        b"<title>Tests &amp; Faults in L&eacute;vy Flights &unknown;</title></article>\n</dblp>\n")


def fake_release(monkeypatch, checksum=None):
    """Serve the release archive, the DBLP dump, and the Retraction Watch CSV, and record each download.

    The stand-in CLI of the archive copies the dump that update-dblp reads to the database path."""
    script = b'#!/bin/sh\n[ "$3" = update-dblp ] && cp "$6" "$4"\nexit 0\n'
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:xz") as bundle:
        member = tarfile.TarInfo("hallucinator-cli-x86_64-unknown-linux-gnu/hallucinator-cli")
        member.size, member.mode = len(script), 0o755
        bundle.addfile(member, io.BytesIO(script))
    archive = buffer.getvalue()
    name = "hallucinator-cli-x86_64-unknown-linux-gnu.tar.xz"
    monkeypatch.setattr(references, "ASSETS", {("Linux", "x86_64"): (name, checksum or hashlib.sha256(archive).hexdigest())})
    monkeypatch.setattr(references.platform, "system", lambda: "Linux")
    monkeypatch.setattr(references.platform, "machine", lambda: "x86_64")
    files = {
        f"{references.RELEASE_URL}/{name}": archive,
        references.DBLP_URL: gzip.compress(DUMP),
        retraction_watch.CSV_URL: (FIXTURES / "retraction_watch.csv").read_bytes(),
    }
    fetched = []

    def fetch(url, target):
        fetched.append(url)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(files[url])

    monkeypatch.setattr(references, "_fetch", fetch)
    return fetched


@pytest.mark.skipif(os.name == "nt", reason="the stand-in CLI is a shell script")
def test_install_tools_installs_the_cli_and_builds_dblp_from_a_local_dump(tmp_path, monkeypatch):
    fetched = fake_release(monkeypatch)
    dump = tmp_path / "dblp.xml.gz"
    dump.write_bytes(gzip.compress(DUMP))
    binary, database, csv_file = references.install_tools(tmp_path / "cache", dblp_dump=dump,
                                                          retraction_csv=FIXTURES / "retraction_watch.csv")
    assert fetched == [f"{references.RELEASE_URL}/hallucinator-cli-x86_64-unknown-linux-gnu.tar.xz"]
    assert binary == tmp_path / "cache" / "hallucinator" / references.VERSION / "hallucinator-cli"
    assert os.access(binary, os.X_OK)
    assert b"<author>Ren&#233; Just</author>" in gzip.decompress(database.read_bytes())
    assert csv_file.read_bytes() == (FIXTURES / "retraction_watch.csv").read_bytes()
    assert sorted(p.name for p in database.parent.iterdir()) == ["0.2.4", "dblp.db", "hallucinator.toml"]
    assert dump.is_file()


@pytest.mark.skipif(os.name == "nt", reason="the stand-in CLI is a shell script")
def test_install_tools_downloads_the_dblp_dump_and_the_retraction_data_without_local_files(tmp_path, monkeypatch):
    fetched = fake_release(monkeypatch)
    _binary, database, csv_file = references.install_tools(tmp_path / "cache")
    assert fetched[1:] == [references.DBLP_URL, retraction_watch.CSV_URL]
    assert database.is_file() and csv_file.is_file()
    assert not (tmp_path / "cache" / "hallucinator" / "dblp.xml.gz").exists()


def test_install_tools_rejects_an_archive_with_a_wrong_checksum(tmp_path, monkeypatch):
    fake_release(monkeypatch, checksum="0" * 64)
    with pytest.raises(tools.ToolError, match="SHA-256"):
        references.install_tools(tmp_path / "cache", retraction_csv=FIXTURES / "retraction_watch.csv")
    assert not (tmp_path / "cache" / "hallucinator" / references.VERSION / "hallucinator-cli").exists()


def test_install_tools_keeps_files_already_present(tmp_path, monkeypatch):
    fetched = fake_release(monkeypatch)
    cache = tmp_path / "cache"
    for path in (cache / "hallucinator" / references.VERSION / "hallucinator-cli", cache / "hallucinator" / "dblp.db",
                 cache / "retraction_watch.csv"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("present", encoding="utf-8")
    references.install_tools(cache)
    assert fetched == []


def test_numeric_entities_rewrites_dtd_entities_and_keeps_xml_entities(tmp_path):
    (tmp_path / "dump.xml.gz").write_bytes(gzip.compress(DUMP))
    references.numeric_entities(tmp_path / "dump.xml.gz", tmp_path / "numeric.xml.gz")
    text = gzip.decompress((tmp_path / "numeric.xml.gz").read_bytes())
    assert b"<author>Ren&#233; Just</author>" in text
    assert b"<title>Tests &amp; Faults in L&#233;vy Flights &unknown;</title>" in text


def test_numeric_entities_rewrites_an_entity_that_spans_two_chunks(tmp_path, monkeypatch):
    monkeypatch.setattr(references, "CHUNK_BYTES", 7)
    (tmp_path / "dump.xml.gz").write_bytes(gzip.compress(DUMP))
    references.numeric_entities(tmp_path / "dump.xml.gz", tmp_path / "numeric.xml.gz")
    assert gzip.decompress((tmp_path / "numeric.xml.gz").read_bytes()) == DUMP.replace(b"&eacute;", b"&#233;")


class _Dropping(BaseHTTPRequestHandler):
    """Serve a payload, cutting the first answer in half as a dropped connection does, and honor byte ranges."""

    payload = bytes(range(256)) * 400
    answers: ClassVar[list[str]] = []
    drop_every_answer = False

    def do_GET(self):
        start = int(self.headers.get("Range", "bytes=0-")[6:].rstrip("-") or 0)
        first = not self.answers
        self.answers.append(self.headers.get("Range", ""))
        self.send_response(206 if start else 200)
        self.send_header("Content-Length", str(len(self.payload) - start))
        self.end_headers()
        body = self.payload[start:]
        self.wfile.write(body[: len(body) // 2] if first or self.drop_every_answer else body)
        self.close_connection = True

    def log_message(self, *args):
        pass


def _serve(handler):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_fetch_resumes_a_dropped_download_from_where_it_stopped(tmp_path):
    handler = type("Handler", (_Dropping,), {"answers": []})
    server = _serve(handler)
    try:
        references._fetch(f"http://127.0.0.1:{server.server_port}/dblp.xml.gz", tmp_path / "dblp.xml.gz")
    finally:
        server.shutdown()
    assert (tmp_path / "dblp.xml.gz").read_bytes() == _Dropping.payload
    assert handler.answers[1] == f"bytes={len(_Dropping.payload) // 2}-"


def test_fetch_reports_a_download_that_keeps_dropping_and_leaves_no_file(tmp_path):
    handler = type("Handler", (_Dropping,), {"answers": [], "drop_every_answer": True})
    server = _serve(handler)
    try:
        with pytest.raises(tools.ToolError, match="run the setup again"):
            references._fetch(f"http://127.0.0.1:{server.server_port}/dblp.xml.gz", tmp_path / "dblp.xml.gz",
                              attempts=2)
    finally:
        server.shutdown()
    assert not (tmp_path / "dblp.xml.gz").exists()

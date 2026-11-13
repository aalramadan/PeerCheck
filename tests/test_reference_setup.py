"""Tests of the setup of the reference check, with stand-ins for the release archive and the downloads."""

from __future__ import annotations

import gzip
import hashlib
import io
import os
import tarfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar

import pytest

from peercheck import dblp, tools
from peercheck.papers import reference_setup, retraction_watch

FIXTURES = Path(__file__).parent / "fixtures" / "references"

DUMP = (b'<?xml version="1.0" encoding="ISO-8859-1"?>\n<dblp>\n<article key="x"><author>Ren&eacute; Just</author>'
        b"<title>Tests &amp; Faults in L&eacute;vy Flights &unknown;</title></article>\n</dblp>\n")


def fake_release(monkeypatch, checksum=None):
    """Serve the release archive, the DBLP dump and its DTD, and the Retraction Watch CSV, and record each download.

    The stand-in CLI of the archive copies the dump that update-dblp reads to the database path."""
    script = b'#!/bin/sh\n[ "$3" = update-dblp ] && cp "$6" "$4"\nexit 0\n'
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:xz") as bundle:
        member = tarfile.TarInfo("hallucinator-cli-x86_64-unknown-linux-gnu/hallucinator-cli")
        member.size, member.mode = len(script), 0o755
        bundle.addfile(member, io.BytesIO(script))
    archive = buffer.getvalue()
    name = "hallucinator-cli-x86_64-unknown-linux-gnu.tar.xz"
    checksum = checksum or hashlib.sha256(archive).hexdigest()
    monkeypatch.setattr(reference_setup, "ASSETS", {("Linux", "x86_64"): (name, checksum)})
    monkeypatch.setattr(reference_setup.platform, "system", lambda: "Linux")
    monkeypatch.setattr(reference_setup.platform, "machine", lambda: "x86_64")
    files = {
        f"{reference_setup.RELEASE_URL}/{name}": archive,
        reference_setup.DBLP_URL: gzip.compress(DUMP),
        reference_setup.DBLP_DTD_URL: b"<!ELEMENT dblp ANY>",
        retraction_watch.CSV_URL: (FIXTURES / "retraction_watch.csv").read_bytes(),
    }
    fetched = []

    def fetch(url, target):
        fetched.append(url)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(files[url])

    monkeypatch.setattr(reference_setup, "_fetch", fetch)
    return fetched


@pytest.mark.skipif(os.name == "nt", reason="the stand-in CLI is a shell script")
def test_install_tools_installs_the_cli_and_builds_dblp_from_the_dump_in_the_cache(tmp_path, monkeypatch):
    fetched = fake_release(monkeypatch)
    dump, dtd, _index = dblp.files(tmp_path / "cache")
    dump.parent.mkdir(parents=True)
    dump.write_bytes(gzip.compress(DUMP))
    dtd.write_bytes(b"<!ELEMENT dblp ANY>")
    binary, database, kept, csv_file = reference_setup.install_tools(tmp_path / "cache",
                                                                retraction_csv=FIXTURES / "retraction_watch.csv")
    assert fetched == [f"{reference_setup.RELEASE_URL}/hallucinator-cli-x86_64-unknown-linux-gnu.tar.xz"]
    assert binary == tmp_path / "cache" / "hallucinator" / reference_setup.VERSION / "hallucinator-cli"
    assert os.access(binary, os.X_OK)
    assert b"<author>Ren&#233; Just</author>" in gzip.decompress(database.read_bytes())
    assert csv_file.read_bytes() == (FIXTURES / "retraction_watch.csv").read_bytes()
    assert sorted(p.name for p in database.parent.iterdir()) == ["0.2.4", "dblp.db", "hallucinator.toml"]
    assert kept == dump and dump.is_file()


@pytest.mark.skipif(os.name == "nt", reason="the stand-in CLI is a shell script")
def test_install_tools_downloads_and_keeps_the_dblp_dump_for_the_conflict_check(tmp_path, monkeypatch):
    fetched = fake_release(monkeypatch)
    _binary, database, dump, csv_file = reference_setup.install_tools(tmp_path / "cache")
    assert fetched[1:] == [reference_setup.DBLP_URL, reference_setup.DBLP_DTD_URL, retraction_watch.CSV_URL]
    assert database.is_file() and csv_file.is_file()
    assert dump.is_file() and dump.with_name("dblp.dtd").is_file()


def test_install_tools_adds_only_the_dblp_dump_to_a_cache_set_up_before_it_was_kept(tmp_path, monkeypatch):
    fetched = fake_release(monkeypatch)
    cache = tmp_path / "cache"
    for path in (reference_setup.binary_path(cache), cache / "hallucinator" / "dblp.db",
                 cache / "retraction_watch.csv"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("present", encoding="utf-8")
    _binary, database, dump, _csv_file = reference_setup.install_tools(cache)
    assert fetched == [reference_setup.DBLP_URL, reference_setup.DBLP_DTD_URL]
    assert database.read_text(encoding="utf-8") == "present"
    assert dump.is_file() and dump.with_name("dblp.dtd").is_file()


def test_install_tools_rejects_an_archive_with_a_wrong_checksum(tmp_path, monkeypatch):
    fake_release(monkeypatch, checksum="0" * 64)
    with pytest.raises(tools.ToolError, match="SHA-256"):
        reference_setup.install_tools(tmp_path / "cache", retraction_csv=FIXTURES / "retraction_watch.csv")
    assert not (tmp_path / "cache" / "hallucinator" / reference_setup.VERSION / "hallucinator-cli").exists()


def test_install_tools_keeps_files_already_present(tmp_path, monkeypatch):
    fetched = fake_release(monkeypatch)
    cache = tmp_path / "cache"
    for path in (reference_setup.binary_path(cache), cache / "hallucinator" / "dblp.db",
                 cache / "retraction_watch.csv", *dblp.files(cache)[:2]):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("present", encoding="utf-8")
    reference_setup.install_tools(cache)
    assert fetched == []


def test_numeric_entities_rewrites_dtd_entities_and_keeps_xml_entities(tmp_path):
    (tmp_path / "dump.xml.gz").write_bytes(gzip.compress(DUMP))
    reference_setup.numeric_entities(tmp_path / "dump.xml.gz", tmp_path / "numeric.xml.gz")
    text = gzip.decompress((tmp_path / "numeric.xml.gz").read_bytes())
    assert b"<author>Ren&#233; Just</author>" in text
    assert b"<title>Tests &amp; Faults in L&#233;vy Flights &unknown;</title>" in text


def test_numeric_entities_rewrites_an_entity_that_spans_two_chunks(tmp_path, monkeypatch):
    monkeypatch.setattr(reference_setup, "CHUNK_BYTES", 7)
    (tmp_path / "dump.xml.gz").write_bytes(gzip.compress(DUMP))
    reference_setup.numeric_entities(tmp_path / "dump.xml.gz", tmp_path / "numeric.xml.gz")
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
        reference_setup._fetch(f"http://127.0.0.1:{server.server_port}/dblp.xml.gz", tmp_path / "dblp.xml.gz")
    finally:
        server.shutdown()
    assert (tmp_path / "dblp.xml.gz").read_bytes() == _Dropping.payload
    assert handler.answers[1] == f"bytes={len(_Dropping.payload) // 2}-"


def test_fetch_reports_a_download_that_keeps_dropping_and_leaves_no_file(tmp_path):
    handler = type("Handler", (_Dropping,), {"answers": [], "drop_every_answer": True})
    server = _serve(handler)
    try:
        with pytest.raises(tools.ToolError, match="run the setup again"):
            reference_setup._fetch(f"http://127.0.0.1:{server.server_port}/dblp.xml.gz", tmp_path / "dblp.xml.gz",
                              attempts=2)
    finally:
        server.shutdown()
    assert not (tmp_path / "dblp.xml.gz").exists()

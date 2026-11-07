"""Tests of the local web page: the commands it runs, the uploads it keeps, and the requests it refuses."""

import http.client
import json
import os
import re
import signal
import subprocess
import sys
import threading
from pathlib import Path
from urllib.parse import quote

import pytest

from peercheck import cli, gui

SAMPLES = Path(__file__).resolve().parents[1] / "samples"


@pytest.fixture
def server(tmp_path):
    """Serve the page of one session from a folder inside a temporary folder, on a free port."""
    root = tmp_path / "session"
    root.mkdir()
    running = gui.Server(0, "icse-2027", root)
    threading.Thread(target=running.serve_forever, daemon=True).start()
    yield running
    running.shutdown()
    running.server_close()


def call(server, method, path, body=None, token=True, host=None, headers=None):
    """Send one request to the server and return its status and body."""
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=300)
    headers = {"Host": host or f"127.0.0.1:{server.server_port}", **(headers or {})}
    if token:
        headers["X-PeerCheck-Token"] = server.token
    connection.request(method, path, body=body, headers=headers)
    reply = connection.getresponse()
    data = reply.read()
    connection.close()
    return reply.status, data


def start_run(server, uploads, options):
    """Upload (field, file) pairs to a new run, start it with the options, and return the outcome."""
    run = json.loads(call(server, "POST", "/api/new")[1])["run"]
    for field, path in uploads:
        status, _ = call(server, "PUT", f"/api/file?run={run}&field={field}&name={path.name}", path.read_bytes())
        assert status == 200
    status, data = call(server, "POST", "/api/start", json.dumps({"run": run, **options}).encode())
    return status, json.loads(data)


def test_papers_command_passes_the_uploaded_files_and_the_chosen_checks_in_order(tmp_path):
    (tmp_path / "authors").mkdir()
    (tmp_path / "authors" / "authors.csv").write_text("paper,first,last,email,affiliation\n")
    arguments = gui.command("papers", {"profile": "fse-2027", "checks": ["hidden-text", "layout"]}, tmp_path)
    assert arguments[:4] == ["--profile", "fse-2027", "papers", str(tmp_path / "pdfs")]
    assert arguments[arguments.index("--authors") + 1] == str(tmp_path / "authors" / "authors.csv")
    assert arguments[arguments.index("--checks") + 1] == "layout,hidden-text"
    assert "--submissions" not in arguments


def test_papers_command_needs_at_least_one_check(tmp_path):
    with pytest.raises(gui.RequestError):
        gui.command("papers", {"profile": "icse-2027", "checks": []}, tmp_path)


def test_reviews_command_keeps_only_the_detectors_and_checks_it_knows(tmp_path):
    arguments = gui.command("reviews", {"profile": "icse-2027", "detectors": ["editlens", "other"], "checks": []},
                            tmp_path)
    assert arguments[arguments.index("--detectors") + 1] == "editlens"
    assert arguments[arguments.index("--checks") + 1] == ""


def test_unknown_kind_of_run_is_refused(tmp_path):
    with pytest.raises(gui.RequestError):
        gui.command("delete", {"profile": "icse-2027"}, tmp_path)


def test_upload_keeps_only_the_base_name_of_a_file(tmp_path):
    assert gui.upload_path(tmp_path, "pdfs", "../../etc/conf-paper1.pdf") == tmp_path / "pdfs" / "conf-paper1.pdf"
    assert gui.upload_path(tmp_path, "pc", "C:\\lists\\pc.csv") == tmp_path / "pc" / "pc.csv"


@pytest.mark.parametrize(("field", "name"), [("scripts", "run.sh"), ("pdfs", ".bashrc"), ("pdfs", "")])
def test_upload_refuses_unknown_fields_and_hidden_or_empty_names(tmp_path, field, name):
    with pytest.raises(gui.RequestError):
        gui.upload_path(tmp_path, field, name)


def test_requests_addressed_to_another_host_are_refused(server):
    assert call(server, "GET", "/", host=f"rebound.example:{server.server_port}")[0] == 403


def test_requests_through_another_port_of_a_local_name_are_answered(server):
    assert call(server, "GET", "/", token=False, host="localhost:9000")[0] == 200
    assert call(server, "GET", "/", token=False, host="localhost")[0] == 200
    assert call(server, "POST", "/api/new", host="127.0.0.1:9000")[0] == 200


def test_uploads_and_runs_need_the_token_of_the_session(server):
    assert call(server, "POST", "/api/new", token=False)[0] == 403
    status, data = call(server, "POST", "/api/new")
    assert status == 200 and json.loads(data)["run"]


def test_page_and_profiles_load_without_the_token(server):
    status, page = call(server, "GET", "/", token=False)
    assert status == 200 and b"<title>PeerCheck</title>" in page
    profiles = json.loads(call(server, "GET", "/api/profiles", token=False)[1])["profiles"]
    assert profiles[0]["key"] == "icse-2027"


def test_profile_outside_the_offered_list_is_refused(server, tmp_path):
    status, data = start_run(server, [], {"kind": "conflicts", "profile": str(tmp_path / "venue.yaml")})
    assert status == 400 and data["error"] == "unknown venue profile"


def test_files_of_an_unknown_run_or_name_are_not_served(server):
    run = json.loads(call(server, "POST", "/api/new")[1])["run"]
    assert call(server, "GET", "/runs/unknown/report.html")[0] == 404
    assert call(server, "GET", f"/runs/{run}/report.html")[0] == 404
    assert call(server, "GET", f"/runs/{run}/../../secret.txt")[0] == 404


def test_run_ids_that_the_session_did_not_issue_are_refused(server, tmp_path):
    (tmp_path / "report.html").write_text("a report that another program left in the temporary folder")
    assert call(server, "GET", "/runs/../report.html", token=False)[0] == 404
    assert call(server, "PUT", "/api/file?run=..&field=pdfs&name=paper1.pdf", b"%PDF-1.4\n")[0] == 400
    assert not (tmp_path / "pdfs").exists()


def test_requests_that_fail_inside_the_server_get_an_answer_with_the_reason(server):
    run = json.loads(call(server, "POST", "/api/new")[1])["run"]
    too_long = quote("\u00e9" * 126 + ".pdf")
    status, data = call(server, "PUT", f"/api/file?run={run}&field=pdfs&name={too_long}", b"%PDF")
    assert status == 400 and json.loads(data)["error"]
    status, data = call(server, "PUT", f"/api/file?run={run}&field=pdfs&name=a.pdf", b"%PDF",
                        headers={"Content-Length": "abc"})
    assert status == 400 and json.loads(data)["error"]
    options = {"run": run, "kind": "papers", "profile": "icse-2027", "checks": 5}
    status, data = call(server, "POST", "/api/start", json.dumps(options).encode())
    assert status == 400 and json.loads(data)["error"]
    assert call(server, "POST", "/api/new", token=False, headers={"X-PeerCheck-Token": "\u00e9\u00e9"})[0] == 403


def test_page_offers_only_the_list_formats_that_peercheck_reads():
    accepted = re.findall(r'accept="([^"]*)"', gui.PAGE.read_text(encoding="utf-8"))
    assert {kind for kinds in accepted for kind in kinds.split(",")} == {".pdf", ".xml", ".csv", ".xlsx"}


@pytest.mark.parametrize("number", [signal.SIGTERM, signal.SIGHUP], ids=lambda number: number.name)
def test_page_deletes_the_folder_of_uploads_when_a_signal_stops_it(tmp_path, number):
    command = [sys.executable, "-m", "peercheck", "gui", "--no-browser", "--host", "127.0.0.1", "--port", "0"]
    environment = {**os.environ, "TMPDIR": str(tmp_path)}
    with subprocess.Popen(command, stdout=subprocess.PIPE, text=True, env=environment) as page:
        try:
            assert "PeerCheck runs at" in page.stdout.readline()
            assert list(tmp_path.glob("peercheck-gui-*"))
            page.send_signal(number)
            assert page.wait(timeout=30) == 0
        finally:
            page.kill()
    assert not list(tmp_path.glob("peercheck-gui-*"))


def test_page_runs_the_conflict_check_and_returns_its_rows(server):
    status, outcome = start_run(server, [("authors", SAMPLES / "authors.csv"), ("pc", SAMPLES / "committee.csv")],
                                {"kind": "conflicts", "profile": "icse-2027"})
    assert status == 200 and outcome["ok"], outcome["log"]
    assert outcome["summary"] == "2 possible conflicts."
    assert sorted(row["Paper"] for row in outcome["rows"]) == ["2", "3"]
    assert call(server, "GET", outcome["workbook"])[0] == 200


def test_page_runs_a_papers_check_and_serves_its_report(server):
    status, outcome = start_run(server, [("pdfs", SAMPLES / "papers" / "conf2027-paper4.pdf")],
                                {"kind": "papers", "profile": "icse-2027", "checks": ["hidden-text"]})
    assert status == 200 and outcome["ok"], outcome["log"]
    assert outcome["summary"] == "1 papers checked, 1 need review."
    reply, page = call(server, "GET", outcome["report"])
    assert reply == 200 and b"hidden-text.white-text" in page


def test_server_in_a_container_listens_on_every_address_but_answers_only_local_names(tmp_path):
    running = gui.Server(0, "icse-2027", tmp_path, host="0.0.0.0")
    threading.Thread(target=running.serve_forever, daemon=True).start()
    try:
        assert running.server_address[0] == "0.0.0.0"
        assert call(running, "GET", "/", token=False, host="localhost:8765")[0] == 200
        assert call(running, "GET", "/", token=False, host="rebound.example:8765")[0] == 403
    finally:
        running.shutdown()
        running.server_close()


def test_gui_command_takes_its_address_and_port_from_the_environment_of_the_docker_image(monkeypatch):
    monkeypatch.setenv("PEERCHECK_GUI_HOST", "0.0.0.0")
    monkeypatch.setenv("PEERCHECK_GUI_PORT", "8765")
    args = cli.parser().parse_args(["gui"])
    assert (args.host, args.port) == ("0.0.0.0", 8765)

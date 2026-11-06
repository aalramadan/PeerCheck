"""Local web page of PeerCheck in plain HTML, CSS, and JavaScript, for people who prefer a browser to the command line.

peercheck gui starts a small web server of the Python standard library on 127.0.0.1 and opens the page in the
browser. The page uploads the chosen files to this server, which keeps them in a temporary folder, runs the same
command as peercheck papers, reviews, or conflicts, and returns its report. Every file stays on this computer, and
the temporary folder is deleted when the server stops. The server answers only requests addressed to 127.0.0.1 or
localhost, which blocks DNS rebinding, and each upload or run needs the token of the session, which only the page
that the server opened holds.
"""

from __future__ import annotations

import json
import re
import secrets
import subprocess
import sys
import tempfile
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import openpyxl

from peercheck import pipeline
from peercheck import profile as profiles

PAGE = Path(__file__).with_name("gui.html")
# The upload fields of the page: a folder field takes many files, a single field takes one list or key file.
FOLDER_FIELDS = ("pdfs", "reviews")
SINGLE_FIELDS = ("authors", "submissions", "canaries", "pc")
KINDS = ("papers", "reviews", "conflicts")
DETECTORS = ("cocodet", "editlens")
REVIEW_CHECKS = ("duplicates", "citations")
RUN_FILES = {"report.html": "text/html; charset=utf-8",
             "report.xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
LOG_LINES = 40


class RequestError(ValueError):
    """A request of the page that the server refuses, with the reason that the page shows."""


def command(kind: str, options: dict, folder: Path) -> list[str]:
    """Return the arguments of peercheck for one run of the page, with the files uploaded to its folder."""
    profile = options["profile"]

    def single(field: str) -> list[str]:
        files = sorted((folder / field).iterdir()) if (folder / field).is_dir() else []
        return [f"--{field}", str(files[0])] if files else []

    reports = ["--out", str(folder / "report.xlsx"), "--html", str(folder / "report.html")]
    if kind == "papers":
        checks = _subset(options.get("checks"), pipeline.PAPER_CHECKS)
        if not checks:
            raise RequestError("choose at least one check")
        return ["--profile", profile, "papers", str(folder / "pdfs"), *reports, *single("authors"),
                *single("submissions"), "--checks", ",".join(checks)]
    if kind == "reviews":
        return ["--profile", profile, "reviews", str(folder / "reviews"), *reports, *single("canaries"),
                "--detectors", ",".join(_subset(options.get("detectors"), DETECTORS)),
                "--checks", ",".join(_subset(options.get("checks"), REVIEW_CHECKS))]
    if kind == "conflicts":
        return ["--profile", profile, "conflicts", *single("authors"), *single("pc"), "--out", str(folder / "report.xlsx")]
    raise RequestError(f"unknown kind of run: {kind}")


def upload_path(folder: Path, field: str, name: str) -> Path:
    """Return where an uploaded file goes in the folder of its run, keeping only the base name of the file."""
    base = Path(name.replace("\\", "/")).name
    if field not in FOLDER_FIELDS + SINGLE_FIELDS:
        raise RequestError(f"unknown field: {field}")
    if not base or base.startswith("."):
        raise RequestError(f"unusable file name: {name}")
    return folder / field / base


def sheet_rows(workbook: Path, sheet: str) -> list[dict]:
    """Return the rows of one sheet of a report as dictionaries keyed by the header, for the table of the page."""
    if not workbook.is_file():
        return []
    book = openpyxl.load_workbook(workbook, read_only=True)
    if sheet not in book.sheetnames:
        return []
    values = list(book[sheet].iter_rows(values_only=True))
    return [dict(zip(values[0], row)) for row in values[1:]] if values else []


class Server(ThreadingHTTPServer):
    """The server of one session, with its token, its temporary folder, and one run at a time."""

    daemon_threads = True

    def __init__(self, port: int, profile: str, root: Path) -> None:
        super().__init__(("127.0.0.1", port), Handler)
        self.profile, self.root = profile, root
        self.token = secrets.token_urlsafe(24)
        self.running = threading.Lock()
        self.hosts = {f"127.0.0.1:{self.server_port}", f"localhost:{self.server_port}"}

    def profiles(self) -> list[dict[str, str]]:
        """Return the profiles that the page offers: the profile of the session first, then the shipped ones."""
        keys = [self.profile] + [key for key in profiles.available() if key != self.profile]
        # A profile given as a path shows only its file name.
        return [{"key": key, "name": profiles.load(key).name, "label": Path(key).name} for key in keys]

    def start(self, request: dict) -> dict:
        """Run one command on the files of a run and return its outcome for the page."""
        folder = self.run_folder(str(request.get("run", "")))
        kind = str(request.get("kind", ""))
        if request.get("profile") not in {p["key"] for p in self.profiles()}:
            raise RequestError("unknown venue profile")
        arguments = command(kind, request, folder)
        if not self.running.acquire(blocking=False):
            raise RequestError("another check is running; wait for it to end")
        try:
            done = subprocess.run([sys.executable, "-m", "peercheck", *arguments], capture_output=True, text=True,
                                  check=False)
        finally:
            self.running.release()
        log = (done.stdout + done.stderr).strip().splitlines()[-LOG_LINES:]
        printed = done.stdout.strip().splitlines()
        link = f"/runs/{folder.name}/"
        return {"ok": done.returncode == 0, "log": "\n".join(log),
                # The last line of a command counts its results, such as "5 papers checked, 3 need review."
                "summary": re.sub(r"\s*Report: .*$", "", printed[-1]) if printed else "",
                "report": link + "report.html" if (folder / "report.html").is_file() else None,
                "workbook": link + "report.xlsx" if (folder / "report.xlsx").is_file() else None,
                "rows": sheet_rows(folder / "report.xlsx", "Conflicts") if kind == "conflicts" else []}

    def run_folder(self, run: str) -> Path:
        """Return the folder of an existing run of this session."""
        folder = self.root / run
        if not run or "/" in run or not folder.is_dir():
            raise RequestError("unknown run")
        return folder


class Handler(BaseHTTPRequestHandler):
    """The requests of the page: the page itself, the profiles, uploads, runs, and the reports of each run."""

    server: Server

    def do_GET(self) -> None:
        if not self._addressed_here():
            return
        path = urlsplit(self.path).path
        if path == "/":
            self._send(HTTPStatus.OK, PAGE.read_bytes(), "text/html; charset=utf-8")
        elif path == "/api/profiles":
            self._json(HTTPStatus.OK, {"profiles": self.server.profiles()})
        elif path.startswith("/runs/"):
            self._run_file(path)
        else:
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:
        if not self._addressed_here() or not self._with_token():
            return
        path = urlsplit(self.path).path
        try:
            if path == "/api/new":
                run = secrets.token_urlsafe(16)
                (self.server.root / run).mkdir()
                self._json(HTTPStatus.OK, {"run": run})
            elif path == "/api/start":
                request = json.loads(self._body() or b"{}")
                if not isinstance(request, dict):
                    raise RequestError("a run needs its options")
                self._json(HTTPStatus.OK, self.server.start(request))
            else:
                self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
        except (RequestError, json.JSONDecodeError) as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})

    def do_PUT(self) -> None:
        if not self._addressed_here() or not self._with_token():
            return
        query = parse_qs(urlsplit(self.path).query)
        try:
            folder = self.server.run_folder(query.get("run", [""])[0])
            target = upload_path(folder, query.get("field", [""])[0], query.get("name", [""])[0])
            target.parent.mkdir(exist_ok=True)
            target.write_bytes(self._body())
            self._json(HTTPStatus.OK, {"saved": target.name})
        except RequestError as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})

    def log_message(self, *args) -> None:
        """Keep the terminal free of one line per request."""

    def _addressed_here(self) -> bool:
        if self.headers.get("Host") in self.server.hosts:
            return True
        self._json(HTTPStatus.FORBIDDEN, {"error": "open the page at 127.0.0.1 or localhost"})
        return False

    def _with_token(self) -> bool:
        if secrets.compare_digest(self.headers.get("X-PeerCheck-Token", ""), self.server.token):
            return True
        self._json(HTTPStatus.FORBIDDEN, {"error": "open the page from the address that peercheck gui printed"})
        return False

    def _body(self) -> bytes:
        return self.rfile.read(int(self.headers.get("Content-Length") or 0))

    def _run_file(self, path: str) -> None:
        parts = path.split("/")
        try:
            folder = self.server.run_folder(parts[2] if len(parts) == 4 else "")
        except RequestError:
            folder = None
        name = parts[-1]
        if folder is None or name not in RUN_FILES or not (folder / name).is_file():
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        extra = {"Content-Disposition": f'attachment; filename="{name}"'} if name.endswith(".xlsx") else {}
        self._send(HTTPStatus.OK, (folder / name).read_bytes(), RUN_FILES[name], extra)

    def _json(self, status: HTTPStatus, data: dict) -> None:
        self._send(status, json.dumps(data, default=str).encode(), "application/json")

    def _send(self, status: HTTPStatus, body: bytes, kind: str, extra: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)


def serve(profile: str, port: int = 0, open_browser: bool = True) -> int:
    """Serve the page on 127.0.0.1 until Ctrl+C, then delete the uploaded files."""
    with tempfile.TemporaryDirectory(prefix="peercheck-gui-") as root:
        server = Server(port, profile, Path(root))
        url = f"http://127.0.0.1:{server.server_port}/?token={server.token}"
        print(f"PeerCheck runs at {url}\nPress Ctrl+C to stop.", flush=True)
        if open_browser:
            webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print()
        finally:
            server.server_close()
    return 0


def _subset(names, allowed: tuple[str, ...]) -> list[str]:
    """Keep the chosen names that the command knows, in the order of the command."""
    chosen = set(names or ())
    return [name for name in allowed if name in chosen]

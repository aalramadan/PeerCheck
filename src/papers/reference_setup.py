"""Setup of the reference check: download the Hallucinator CLI, the DBLP dump with its DTD, and the Retraction Watch
CSV into the cache, then build the offline DBLP database."""

from __future__ import annotations

import gzip
import hashlib
import html.entities
import platform
import re
import shutil
import subprocess
import tarfile
import urllib.request
import zipfile
from pathlib import Path

from peercheck import dblp, tools
from peercheck.papers import retraction_watch

VERSION = "0.2.4"
RELEASE_URL = f"https://github.com/gianlucasb/hallucinator/releases/download/v{VERSION}"
# CLI archive and SHA-256 of each platform, from the sha256.sum file of the release.
ASSETS = {
    ("Linux", "x86_64"): (
        "hallucinator-cli-x86_64-unknown-linux-gnu.tar.xz",
        "c3ce1d4081e631151b9493c05c2777b87062ddf3a4c08391dcc6b47a8637a4bc",
    ),
    ("Darwin", "arm64"): (
        "hallucinator-cli-aarch64-apple-darwin.tar.xz",
        "a71db8cd8a2f1434f2722837729b72ab3a946c71cc5ff5aee9f10bb2f25efac4",
    ),
    ("Darwin", "x86_64"): (
        "hallucinator-cli-x86_64-apple-darwin.tar.xz",
        "8c58e033d86fe675d26aab88ed2d079f39b863ad8cf13ada9d7de02163b6e9d8",
    ),
    ("Windows", "AMD64"): (
        "hallucinator-cli-x86_64-pc-windows-msvc.zip",
        "d48a958c255d1b01a0ff5cf626b2f13ad969026009e8778d488833862871ba7c",
    ),
}
# The dump that the DBLP builder of Hallucinator downloads when it gets no local file.
DBLP_URL = "https://dblp.uni-trier.de/xml/dblp.xml.gz"
DBLP_DTD_URL = "https://dblp.uni-trier.de/xml/dblp.dtd"
# The DBLP dump of about 1.1 GB comes slowly, and a connection that drops resumes this many times.
DOWNLOAD_ATTEMPTS = 20
NAMED_ENTITY = re.compile(rb"&([A-Za-z][A-Za-z0-9]*);")
XML_ENTITIES = (b"amp", b"lt", b"gt", b"quot", b"apos")
CHUNK_BYTES = 1 << 24


def binary_path(cache: Path) -> Path:
    """Return the place of the Hallucinator CLI in a cache folder."""
    name = "hallucinator-cli.exe" if platform.system() == "Windows" else "hallucinator-cli"
    return cache / "hallucinator" / VERSION / name


def install_tools(cache: Path | None = None, retraction_csv: Path | None = None, refresh: bool = False) -> list[Path]:
    """Fill the cache with the Hallucinator CLI, the DBLP dump and its offline database, and the Retraction Watch CSV.

    The CLI archive must match the SHA-256 that the release states. A local CSV replaces the download of the
    Retraction Watch data. Files already present stay unless refresh is set. Returns the paths of the binary, the
    database, the dump, and the CSV.
    """
    cache = Path(cache or tools.cache_dir()).expanduser()
    binary, database = binary_path(cache), cache / "hallucinator" / "dblp.db"
    csv_file = cache / "retraction_watch.csv"
    if refresh or not binary.is_file():
        _install_binary(binary)
    dump, dtd, _index = dblp.files(cache)
    for url, target in ((DBLP_URL, dump), (DBLP_DTD_URL, dtd)):
        if refresh or not target.is_file():
            _fetch(url, target)
    if refresh or not database.is_file():
        _build_dblp(binary, database, dump)
    if refresh or not csv_file.is_file():
        partial = csv_file.with_suffix(".partial")
        if retraction_csv:
            shutil.copyfile(retraction_csv, partial)
        else:
            _fetch(retraction_watch.CSV_URL, partial)
        partial.replace(csv_file)
    return [binary, database, dump, csv_file]


def _install_binary(target: Path) -> None:
    asset = ASSETS.get((platform.system(), platform.machine()))
    if asset is None:
        raise tools.ToolError(f"Hallucinator {VERSION} ships no CLI for {platform.system()} {platform.machine()}; "
                              "build it from source and set the binary option")
    name, checksum = asset
    target.parent.mkdir(parents=True, exist_ok=True)
    archive = target.parent / name
    _fetch(f"{RELEASE_URL}/{name}", archive)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if digest != checksum:
        archive.unlink()
        raise tools.ToolError(f"the SHA-256 of {name} is {digest}, not {checksum} as the release states")
    partial = target.with_suffix(".partial")
    partial.write_bytes(_member(archive, target.name))
    partial.chmod(0o755)
    partial.replace(target)
    archive.unlink()


def _member(archive: Path, name: str) -> bytes:
    """Return the bytes of the archive member with the given file name, wherever it sits in the archive."""
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as bundle:
            member = next((m for m in bundle.namelist() if m.rsplit("/", 1)[-1] == name), None)
            if member:
                return bundle.read(member)
    else:
        with tarfile.open(archive) as bundle:
            member = next((m for m in bundle.getmembers() if m.isfile() and m.name.rsplit("/", 1)[-1] == name), None)
            handle = bundle.extractfile(member) if member else None
            if handle:
                return handle.read()
    raise tools.ToolError(f"{archive.name} holds no file named {name}")


def _build_dblp(binary: Path, target: Path, dump: Path) -> None:
    partial, numeric = target.with_suffix(".partial"), target.with_name("dblp-numeric.xml.gz")
    for leftover in (partial, Path(f"{partial}-wal"), Path(f"{partial}-shm")):
        leftover.unlink(missing_ok=True)
    numeric_entities(dump, numeric)
    config = target.parent / "hallucinator.toml"
    config.write_text("", encoding="utf-8")
    command = [str(binary), "--config", str(config), "update-dblp", str(partial), "--from-file", str(numeric)]
    done = subprocess.run(command, check=False, cwd=target.parent, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    numeric.unlink()
    if done.returncode != 0 or not partial.is_file():
        lines = [line for line in done.stderr.splitlines() if line.strip()]
        raise tools.ToolError(f"building the DBLP database failed: {lines[-1] if lines else done.returncode}")
    partial.replace(target)


def numeric_entities(dump: Path, target: Path) -> None:
    """Copy a gzipped DBLP dump with each named character entity written as a numeric character reference.

    The dump names characters such as the e with acute accent through entities of dblp.dtd. The DBLP builder
    of Hallucinator 0.2.4 reads only the five entities of XML itself and drops every title and author name
    that holds another one. A work with such a title is then missing from the database.
    """
    def numeric(match: re.Match) -> bytes:
        code = html.entities.name2codepoint.get(match.group(1).decode())
        return match.group(0) if match.group(1) in XML_ENTITIES or code is None else b"&#%d;" % code

    with gzip.open(dump, "rb") as source, gzip.open(target, "wb", compresslevel=1) as sink:
        rest = b""
        for chunk in iter(lambda: source.read(CHUNK_BYTES), b""):
            # Cut at the last line end so that no entity spans two chunks.
            data = rest + chunk
            cut = data.rfind(b"\n") + 1
            sink.write(NAMED_ENTITY.sub(numeric, data[:cut]))
            rest = data[cut:]
        sink.write(NAMED_ENTITY.sub(numeric, rest))


def _fetch(url: str, target: Path, attempts: int = DOWNLOAD_ATTEMPTS) -> None:
    """Download a public file of a published tool or dataset, resuming after a dropped connection."""
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".partial")
    partial.unlink(missing_ok=True)
    expected = None
    for _ in range(attempts):
        done = partial.stat().st_size if partial.exists() else 0
        headers = {"User-Agent": "PeerCheck"} | ({"Range": f"bytes={done}-"} if done else {})
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=120) as response:
                # A server that ignores the range sends the whole file again.
                resumed = done and response.status == 206
                length = response.headers.get("Content-Length")
                expected = (done if resumed else 0) + int(length) if length else None
                with partial.open("ab" if resumed else "wb") as handle:
                    shutil.copyfileobj(response, handle)
        except OSError:
            continue
        if expected is None or partial.stat().st_size >= expected:
            partial.replace(target)
            return
    size = partial.stat().st_size if partial.exists() else 0
    partial.unlink(missing_ok=True)
    raise tools.ToolError(f"the download of {url} stopped after {size} of {expected or 'unknown'} bytes; "
                          "run the setup again")

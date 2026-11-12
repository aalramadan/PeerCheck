"""Reference check: Hallucinator looks up each cited work in local bibliographic databases, and the
Retraction Watch data marks cited works that carry a retraction notice.

Hallucinator 0.2.4 (github.com/gianlucasb/hallucinator, AGPL-3.0) is the checker that the organizers of
ACSAC 2025 and ICWSM 2026 ran. PeerCheck runs its unchanged command-line binary as a separate process and
reads its JSON report. A reference matches a database record when the titles agree at a fuzzy ratio of at
least 0.95 and the author lists overlap. ``install_tools`` downloads the binary, builds the offline DBLP
database, and fetches the Retraction Watch CSV into the cache. Before the build it rewrites the named
character entities of the DBLP dump as numeric references, since the builder of 0.2.4 drops every title and
author name that holds a named entity.

Options under ``checks.references`` of a profile:

- ``enabled`` (default true): the pipeline runs the check only when the profile leaves it on.
- ``online`` (default true): look up references online beside the local databases. False keeps the check
  offline, with no network connection, whatever ``online_titles`` says.
- ``online_titles`` (default true): send the titles of the references that the local databases do not hold to
  every online source of Hallucinator, such as CrossRef, arXiv, Semantic Scholar, OpenAlex, Europe PMC, PubMed, and
  Open Library, and pass the keys CROSSREF_MAILTO, S2_API_KEY, and OPENALEX_KEY. The check first looks every reference
  up offline, since the local DBLP copy answers within seconds while each online source answers slowly and limits its
  requests. Only the references that stay unverified then go online. The title of a fabricated reference is text
  of the submission,
  therefore organizers who keep that text in house set this option to false. The check then looks up only the
  DOI of a reference at doi.org, which forwards the request to the agency of the DOI such as Crossref, and its
  arXiv ID at export.arxiv.org. These lookups send public identifiers only.
- ``cache`` (default ``tools.cache_dir()``, which is ``$XDG_CACHE_HOME/peercheck`` or
  ``~/.cache/peercheck``): the folder of ``install_tools``.
- ``binary``, ``dblp_db``, ``retraction_csv``: paths that replace the files of the cache.
- ``acl_db``, ``arxiv_db``, ``openalex_db`` (default none): further offline databases built with
  ``hallucinator-cli update-acl``, ``update-arxiv``, or ``update-openalex``. Each one replaces the online
  source of the same name.
- ``local_corpus`` (default none): a Hallucinator local corpus, such as recent ICSE papers imported with
  ``hallucinator-cli import-icse`` or references marked safe in earlier reports.
- ``timeout`` (default 600): seconds before the run on one PDF stops.

Findings: ``references.not-found`` and ``references.author-mismatch`` (WARNING, the reference text as
evidence), ``references.identifier-mismatch`` (WARNING, a DOI or arXiv ID that resolves to another work,
possible only with online lookups), ``references.retracted`` (WARNING, the nature and date of the notice),
``references.summary`` (INFO, the counts), and ``references.error`` (WARNING, the check could not run).
"""

from __future__ import annotations

import dataclasses
import gzip
import hashlib
import html.entities
import json
import os
import platform
import re
import shutil
import subprocess
import tarfile
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

from peercheck import tools
from peercheck.findings import Finding, Severity
from peercheck.models import Paper
from peercheck.papers import retraction_watch
from peercheck.profile import Profile

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
# Every source that Hallucinator queries over the network, by the name that --disable-dbs takes.
ONLINE_SOURCES = (
    "CrossRef", "arXiv", "DBLP", "Semantic Scholar", "ACL Anthology", "Europe PMC", "PubMed", "DOI",
    "OpenAlex", "GovInfo", "PatentsView", "Standards", "Open Library", "SSRN",
)
# Offline databases, each replacing the online source of the same name: source, CLI flag, profile option.
OFFLINE_DATABASES = (
    ("DBLP", "--dblp-offline", "dblp_db"),
    ("ACL Anthology", "--acl-offline", "acl_db"),
    ("arXiv", "--arxiv-offline", "arxiv_db"),
    ("OpenAlex", "--openalex-offline", "openalex_db"),
)
KEY_VARIABLES = ("CROSSREF_MAILTO", "S2_API_KEY", "OPENALEX_KEY")
PROXY_VARIABLES = ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "NO_PROXY", "https_proxy", "http_proxy", "no_proxy")
EVIDENCE_LIMIT = 200
DOI_IN_TEXT = re.compile(r"10\.\d{4,9}/[^\s\"]+")
# Hallucinator turns a line break inside a DOI into a space, such as after the slash or before digits after a period.
DOI_BREAK = re.compile(r"(10\.\d{4,9}/)\s+|(?<=\.)\s+(?=\d)")
ARXIV_IN_TEXT = re.compile(
    r"(?:arxiv:?\s*|arxiv\.org/(?:abs|pdf)/)(\d{4}\.\d{4,5}(?:v\d+)?|[a-z-]+(?:\.[a-z]{2})?/\d{7}(?:v\d+)?)",
    re.IGNORECASE,
)
UNVERIFIED = ("not_found", "inconclusive")
# The dump that the DBLP builder of Hallucinator downloads when it gets no local file.
DBLP_URL = "https://dblp.uni-trier.de/xml/dblp.xml.gz"
# The DBLP dump of about 1.1 GB comes slowly, and a connection that drops resumes this many times.
DOWNLOAD_ATTEMPTS = 20
NAMED_ENTITY = re.compile(rb"&([A-Za-z][A-Za-z0-9]*);")
XML_ENTITIES = (b"amp", b"lt", b"gt", b"quot", b"apos")
CHUNK_BYTES = 1 << 24
BIB_ESCAPES = str.maketrans({"{": "", "}": "", "\\": "", "%": r"\%", "&": r"\&", "#": r"\#", "_": r"\_", "$": r"\$"})


@dataclass(frozen=True)
class Settings:
    """Options of one run, resolved against the cache."""

    online: bool
    online_titles: bool
    binary: Path
    offline: dict[str, Path]
    local_corpus: Path | None
    retraction_csv: Path
    timeout: float


@dataclass(frozen=True)
class Reference:
    """One reference of the JSON report of Hallucinator."""

    number: int
    title: str
    text: str
    status: str
    sources: tuple[str, ...] = ()
    failed: tuple[str, ...] = ()
    authors: tuple[str, ...] = ()
    found_authors: tuple[str, ...] = ()
    source: str = ""
    author_mismatch: bool = False
    bad_doi: bool = False
    bad_arxiv: bool = False
    dois: tuple[str, ...] = ()
    arxiv_id: str = ""


def check(paper: Paper, profile: Profile, workdir: Path) -> list[Finding]:
    """Look up every reference of a submission and report the references that no database confirms."""
    settings = settings_from(profile.options("references"))
    folder = workdir / "references"
    try:
        folder.mkdir(parents=True, exist_ok=True)
        refs = _hallucinator(settings, paper.pdf, folder, f"paper-{paper.paper_id}", _disabled(settings))
        if settings.online_titles:
            refs = _online_lookups(settings, refs, folder, f"paper-{paper.paper_id}")
        elif settings.online and "arXiv" not in settings.offline:
            refs = _arxiv_lookups(settings, refs, folder, f"paper-{paper.paper_id}")
    except (tools.ToolError, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        return [Finding("references.error", Severity.WARNING, f"The reference check did not run: {exc}")]
    if not refs:
        return [Finding("references.error", Severity.WARNING, "Hallucinator found no references in the PDF")]
    findings = [finding for ref in refs for finding in _lookup_findings(ref)]
    findings.extend(_retraction_findings(refs, settings.retraction_csv))
    findings.append(_summary(refs, settings))
    return findings


def settings_from(options: dict) -> Settings:
    """Resolve the options of a profile against the cache and the defaults."""
    cache = Path(options.get("cache") or tools.cache_dir()).expanduser()
    tool = cache / "hallucinator"
    offline = {"DBLP": tool / "dblp.db"}
    for source, _flag, key in OFFLINE_DATABASES:
        if options.get(key):
            offline[source] = Path(options[key]).expanduser()
    online = bool(options.get("online", True))
    return Settings(
        online=online,
        online_titles=online and bool(options.get("online_titles", True)),
        binary=Path(options.get("binary") or tool / VERSION / _binary_name()).expanduser(),
        offline=offline,
        local_corpus=Path(options["local_corpus"]).expanduser() if options.get("local_corpus") else None,
        retraction_csv=Path(options.get("retraction_csv") or cache / "retraction_watch.csv").expanduser(),
        timeout=float(options.get("timeout", 600)),
    )


def install_tools(cache: Path | None = None, dblp_dump: Path | None = None, retraction_csv: Path | None = None,
                  refresh: bool = False) -> list[Path]:
    """Fill the cache with the Hallucinator CLI, its offline DBLP database, and the Retraction Watch CSV.

    The CLI archive must match the SHA-256 that the release states. A local dblp.xml.gz or CSV replaces the
    download of that file. Files already present stay unless refresh is set. Returns the paths of the binary,
    the database, and the CSV.
    """
    cache = Path(cache or tools.cache_dir()).expanduser()
    tool = cache / "hallucinator"
    binary, database, csv_file = tool / VERSION / _binary_name(), tool / "dblp.db", cache / "retraction_watch.csv"
    if refresh or not binary.is_file():
        _install_binary(binary)
    if refresh or not database.is_file():
        dump = dblp_dump or tool / "dblp.xml.gz"
        if not dblp_dump:
            _fetch(DBLP_URL, dump)
        _build_dblp(binary, database, dump)
        if not dblp_dump:
            dump.unlink()
    if refresh or not csv_file.is_file():
        partial = csv_file.with_suffix(".partial")
        if retraction_csv:
            shutil.copyfile(retraction_csv, partial)
        else:
            _fetch(retraction_watch.CSV_URL, partial)
        partial.replace(csv_file)
    return [binary, database, csv_file]


def _disabled(settings: Settings) -> list[str]:
    """Return the online sources of the first run, which allows only the DOI lookups of the identifier mode."""
    allowed = {"DOI"} if settings.online and not settings.online_titles else set()
    return [name for name in ONLINE_SOURCES if name not in allowed and name not in settings.offline]


def _hallucinator(settings: Settings, source: Path, folder: Path, stem: str, disabled: list[str],
                  offline: bool = True) -> list[Reference]:
    """Run the CLI on a PDF or a .bib file and return its references, or [] if it extracted none."""
    if not settings.binary.is_file():
        raise tools.ToolError(f"Hallucinator is not installed at {settings.binary}; run peercheck setup")
    report, log = folder / f"{stem}.json", folder / f"{stem}.log"
    report.unlink(missing_ok=True)
    config = folder / "hallucinator.toml"
    # An empty configuration file keeps a user's own Hallucinator settings, such as a web search, out of the run.
    config.write_text("", encoding="utf-8")
    command = [str(settings.binary), "check", "--config", str(config), "--no-color", "--no-searxng",
               "--json", str(report), "--output", str(log)]
    if disabled:
        command += ["--disable-dbs", ",".join(disabled)]
    if offline:
        for name, flag, _key in OFFLINE_DATABASES:
            if name in settings.offline:
                if not settings.offline[name].is_file():
                    raise tools.ToolError(f"the offline {name} database is missing at {settings.offline[name]}; "
                                    "run peercheck setup")
                command += [flag, str(settings.offline[name])]
        if settings.local_corpus:
            command += ["--local-corpus", str(settings.local_corpus)]
    command.append(str(source))
    try:
        done = subprocess.run(command, check=False, cwd=folder, env=_environment(folder, settings),
                              capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=settings.timeout)
    except subprocess.TimeoutExpired as exc:
        raise tools.ToolError(f"Hallucinator did not finish within {settings.timeout:g} seconds") from exc
    if done.returncode != 0:
        lines = [line for line in done.stderr.splitlines() if line.strip()]
        raise tools.ToolError(lines[-1] if lines else f"Hallucinator stopped with exit code {done.returncode}")
    if not report.is_file():
        return []
    return parse_report(json.loads(report.read_text(encoding="utf-8")))


def parse_report(data: list) -> list[Reference]:
    """Turn the JSON report of one file into references, in the order of the reference list."""
    refs = []
    for entry in data[0].get("references", []) if data else []:
        text = entry.get("raw_citation") or ""
        doi_info, arxiv_info = entry.get("doi_info") or {}, entry.get("arxiv_info") or {}
        dois = dict.fromkeys(d for d in [doi_info.get("doi", "")] + _dois(text) if retraction_watch.normalize_doi(d))
        arxiv = ARXIV_IN_TEXT.search(text)
        results = entry.get("db_results") or []
        refs.append(Reference(
            number=int(entry.get("original_number") or len(refs) + 1),
            title=entry.get("title") or "",
            text=text,
            status=entry.get("status") or "",
            sources=tuple(dict.fromkeys(r["db"] for r in results if r.get("status") != "skipped")),
            failed=tuple(entry.get("failed_dbs") or ()),
            authors=tuple(entry.get("ref_authors") or ()),
            found_authors=tuple(entry.get("found_authors") or ()),
            source=entry.get("source") or "",
            author_mismatch=any(r.get("status") == "author_mismatch" for r in results),
            bad_doi=doi_info.get("valid") is False,
            bad_arxiv=arxiv_info.get("valid") is False,
            dois=tuple(dois),
            arxiv_id=arxiv_info.get("arxiv_id") or (arxiv.group(1) if arxiv else ""),
        ))
    return sorted(refs, key=lambda ref: ref.number)


def _arxiv_lookups(settings: Settings, refs: list[Reference], folder: Path, stem: str) -> list[Reference]:
    """Look up the arXiv IDs of the unverified references through Hallucinator alone with its arXiv source.

    A .bib file holds only references with an arXiv ID. For those, the arXiv source of Hallucinator asks for
    the ID and never for the title."""
    pending = [ref for ref in refs if ref.status in UNVERIFIED and ref.arxiv_id]
    if not pending:
        return refs
    bib = folder / f"{stem}-arxiv.bib"
    bib.write_text("".join(_bib_entry(i, ref) for i, ref in enumerate(pending, 1)), encoding="utf-8")
    others = [name for name in ONLINE_SOURCES if name != "arXiv"]
    return _merged(refs, pending, _hallucinator(settings, bib, folder, f"{stem}-arxiv", others, offline=False))


def _online_lookups(settings: Settings, refs: list[Reference], folder: Path, stem: str) -> list[Reference]:
    """Look up online the references that the local databases leave unverified, with their titles and identifiers.

    The online sources that a local database replaces, such as DBLP, stay off, since the first run asked them."""
    pending = [ref for ref in refs if ref.status in UNVERIFIED]
    if not pending:
        return refs
    bib = folder / f"{stem}-online.bib"
    bib.write_text("".join(_bib_entry(i, ref, with_doi=True) for i, ref in enumerate(pending, 1)), encoding="utf-8")
    local = [name for name in ONLINE_SOURCES if name in settings.offline]
    return _merged(refs, pending, _hallucinator(settings, bib, folder, f"{stem}-online", local, offline=False))


def _merged(refs: list[Reference], pending: list[Reference], answers: list[Reference]) -> list[Reference]:
    """Return the references with the answers of a second run, whose numbers count the pending references from 1."""
    updated = {ref.number: ref for ref in refs}
    for answer in answers:
        if 0 < answer.number <= len(pending) and answer.status not in ("skipped", ""):
            ref = pending[answer.number - 1]
            updated[ref.number] = dataclasses.replace(
                ref, status=answer.status, source=answer.source, found_authors=answer.found_authors,
                author_mismatch=answer.author_mismatch, sources=ref.sources + answer.sources,
                failed=ref.failed + answer.failed,
            )
    return [updated[ref.number] for ref in refs]


def _bib_entry(key: int, ref: Reference, with_doi: bool = False) -> str:
    authors = " and ".join(name.translate(BIB_ESCAPES) for name in ref.authors)
    fields = [f"  title = {{{ref.title.translate(BIB_ESCAPES)}}}", f"  author = {{{authors}}}"]
    if ref.arxiv_id:
        fields += [f"  eprint = {{{ref.arxiv_id}}}", "  archivePrefix = {arXiv}"]
    if with_doi and ref.dois:
        fields.append(f"  doi = {{{ref.dois[0]}}}")
    return f"@misc{{ref{key},\n" + ",\n".join(fields) + ",\n}\n"


def _lookup_findings(ref: Reference) -> list[Finding]:
    label = f'Reference [{ref.number}] "{_clip(ref.title, 90)}"'
    evidence = _clip(ref.text, EVIDENCE_LIMIT)
    if ref.status in UNVERIFIED:
        where = ", ".join(ref.sources) or "any database"
        failed = f"; the lookup failed at {', '.join(ref.failed)}" if ref.failed else ""
        return [Finding("references.not-found", Severity.WARNING, f"{label} was not found in {where}{failed}",
                        evidence=evidence)]
    if ref.status != "mismatch":
        return []
    findings = []
    if ref.bad_doi or ref.bad_arxiv:
        what = "DOI" if ref.bad_doi else "arXiv ID"
        findings.append(Finding("references.identifier-mismatch", Severity.WARNING,
                                f"{label} gives a {what} that does not resolve to this work", evidence=evidence))
    if ref.author_mismatch or not findings:
        names = ", ".join(ref.found_authors[:4]) + (" et al." if len(ref.found_authors) > 4 else "")
        findings.append(Finding("references.author-mismatch", Severity.WARNING,
                                f"{label} matches a title in {ref.source or 'a database'} whose authors differ: {names}",
                                evidence=evidence))
    return findings


def _retraction_findings(refs: list[Reference], path: Path) -> list[Finding]:
    if not path.is_file():
        return [Finding("references.error", Severity.WARNING,
                        f"The Retraction Watch data is missing at {path}; run peercheck setup")]
    try:
        index = retraction_watch.load(path)
    except (OSError, ValueError) as exc:
        return [Finding("references.error", Severity.WARNING, f"The Retraction Watch data is unreadable: {exc}")]
    findings = []
    for ref in refs:
        for doi, notices in retraction_watch.match(ref.dois, index).items():
            notice = retraction_watch.in_force(notices)
            if notice:
                findings.append(Finding(
                    "references.retracted", Severity.WARNING,
                    f'Reference [{ref.number}] "{_clip(ref.title, 90)}" carries a Retraction Watch notice: '
                    f"{notice.nature} of {notice.date}",
                    evidence=_clip(f"DOI {doi}. Reason: {notice.reason}", EVIDENCE_LIMIT),
                ))
                break
    return findings


def _summary(refs: list[Reference], settings: Settings) -> Finding:
    counts = {status: sum(1 for ref in refs if ref.status == status) for status in ("verified", "mismatch", "skipped")}
    missing = sum(1 for ref in refs if ref.status in UNVERIFIED)
    mode = ("with online title lookups" if settings.online_titles
            else "with DOI and arXiv ID lookups" if settings.online else "offline")
    sources = ", ".join(sorted(settings.offline) + (["Local Corpus"] if settings.local_corpus else []))
    return Finding(
        "references.summary", Severity.INFO,
        f"Hallucinator checked {len(refs)} references {mode} against {sources}: {counts['verified']} found, "
        f"{missing} not found, {counts['mismatch']} with other authors or identifiers, {counts['skipped']} skipped",
    )


def _dois(text: str) -> list[str]:
    found = []
    # The text with its breaks joined adds a DOI that a line end cut, and the text as it is keeps one that ends a
    # sentence before a number, such as a year.
    for raw in DOI_IN_TEXT.findall(text) + DOI_IN_TEXT.findall(DOI_BREAK.sub(r"\1", text)):
        doi = raw.rstrip(".,;\"'\u201d\u2019")
        # A closing bracket belongs to the DOI only when the DOI also opens one, as in SICI DOIs.
        while doi and doi[-1] in ")]" and doi.count(doi[-1]) > doi.count("(" if doi[-1] == ")" else "["):
            doi = doi[:-1].rstrip(".,;")
        found.append(doi)
    return found


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def _environment(home: Path, settings: Settings) -> dict[str, str]:
    """Return a bare environment, which keeps the keys and settings of the user away from offline runs."""
    names = ["PATH", "SYSTEMROOT", "TEMP", "TMP"]
    if settings.online:
        names += PROXY_VARIABLES
    if settings.online_titles:
        names += KEY_VARIABLES
    env = {name: os.environ[name] for name in names if os.environ.get(name)}
    env.update({"HOME": str(home), "LANG": "C.UTF-8"})
    return env


def _binary_name() -> str:
    return "hallucinator-cli.exe" if platform.system() == "Windows" else "hallucinator-cli"


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

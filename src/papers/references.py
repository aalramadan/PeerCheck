"""Reference check: each cited work is looked up in the local DBLP copy and in online indexes, and the Retraction
Watch data marks the cited works that carry a retraction notice. external/hallucinator/PORT.md describes the lookups,
the findings, and the options."""

from __future__ import annotations

import collections
import concurrent.futures
import contextlib
import dataclasses
import datetime
import itertools
import json
import os
import re
import sqlite3
import subprocess
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from peercheck import tools
from peercheck.findings import Finding, Severity, excerpt
from peercheck.models import Paper
from peercheck.papers import open_indexes, reference_list, reference_match, reference_setup, retraction_watch
from peercheck.papers.lookup_cache import LookupCache
from peercheck.papers.paper_processes import processors
from peercheck.papers.reference_match import Citation
from peercheck.profile import Profile, ProfileError

# Every online source that the code of Hallucinator names, by the name that --disable-dbs takes.
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
# The online run asks these sources, which hold articles and papers. Of the others, PeerCheck asks the indexes of
# arXiv preprints, DOIs, and OpenAlex itself, and the rest holds other kinds of works, is slow, or needs a key.
RUN_SOURCES = ("CrossRef", "PubMed", "ACL Anthology")
# A warning rests on the answer of each of these sources, which hold the most articles and papers.
CORE_SOURCES = ("DBLP", "CrossRef", "OpenAlex")
# Hallucinator gives the address of a DBLP record, which ends in the key of the record.
DBLP_RECORD_URL = "https://dblp.org/rec/"
# The registration agencies whose records PeerCheck reads, by the name of doi.org, with their names in a report.
REGISTRIES = {"Crossref": "CrossRef", "DataCite": "DataCite"}
# The online run gets these variables of the user beside a bare environment.
ONLINE_VARIABLES = ("CROSSREF_MAILTO", "HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "NO_PROXY", "https_proxy",
                    "http_proxy", "no_proxy")
EVIDENCE_LIMIT, TITLE_LIMIT, NAMES_LIMIT = 200, 90, 4
UNCONFIRMED = ("not found, as is common for a book, a report, a talk, a web page, a dataset, a title of fewer than "
               "four words, or a work registered in another script or at another DOI agency")
FAILED_LOOKUP = "not looked up, since the lookup failed at {sources}. A later run repeats the lookup"
OPENALEX_KEY_NOTE = ("OpenAlex did not answer every request. A free key in OPENALEX_KEY raises its daily limit from 100 "
                     "to 1,000 searches.")
PASSED_OVER = ("not looked up. Such an entry hides a work for the review, names a web page, or bears no title of four "
               "words or more")
DOI_IN_TEXT = re.compile(r"10\.\d{4,9}/[^\s\",]+")
# Hallucinator turns a line break inside a DOI into a space, such as after the slash or before digits after a period.
DOI_BREAK = re.compile(r"(10\.\d{4,9}/)\s+|(?<=\.)\s+(?=\d)")
# An arXiv ID follows the word arXiv, the abs/ of an address of arXiv or of a CoRR entry, or the address of its PDF.
ARXIV_IN_TEXT = re.compile(
    r"(?:arxiv:?\s*|\babs/|arxiv\.org/pdf/)(\d{4}\.\d{4,5}(?:v\d+)?|[a-z-]+/\d{7}(?:v\d+)?)", re.IGNORECASE)
# What an entry adds to the ID that arXiv registers: the space that a line end leaves after the period of an ID, and
# the subject class of an old ID, since arXiv registers cs.SE/0601001 as cs/0601001.
ARXIV_EXTRA = re.compile(
    r"((?:arxiv:?\s*|\babs/)\d{4}\.)\s+(?=\d{4,5}(?!\d))|(?<=[a-z])\.[a-z]{2}(?=/\d{7}(?!\d))", re.IGNORECASE)
# Another source can still confirm a reference in one of these states. A record with other authors leaves the
# reference open, since two works may bear one title.
OPEN = ("not_found", "mismatch")
# A source looked a reference up when its result bears one of these marks, and failed or passed otherwise.
ANSWERED = ("match", "no_match", "author_mismatch")
# What the record of a DOI or an arXiv ID is to a reference.
CITED_WORK, OTHER_AUTHORS, NO_AUTHOR, OTHER_WORK, NOTHING = "cited work", "other authors", "no author", "other work", ""
# A run fails with one of these, such as a missing binary, a report that is no JSON, or a report in another form.
RUN_ERRORS = (tools.ToolError, OSError, ValueError, LookupError, TypeError, AttributeError)
# Hallucinator names its own update command for a database that is empty or from an older version.
STALE_DATABASE = re.compile(r"update-dblp|Query returned no rows")
# Papers that go through the local databases at the same time, each in a process of Hallucinator.
LOCAL_RUNS = min(8, processors())
# Requests that an open index answers at the same time.
INDEX_RUNS = 4
# A source that leaves this many requests in a row without an answer gets no further request in that run.
MOST_FAILURES = 3
# Seconds that the online run gets for each of its references beside the timeout of a run.
ONLINE_SECONDS = 10
# Seconds that an index gets per title in a run before it gets no further request: one timeout for each group of
# requests, which is more than the 3.1 seconds per request that the pace of OpenReview takes.
INDEX_SECONDS = open_indexes.TIMEOUT / INDEX_RUNS
LIST_FONT_SIZE, LIST_LEADING, LIST_MARGIN = 8.0, 10.0, 36.0
# A range of two years is no range of pages.
YEARS = r"(?:19|20)\d\d\s*(?:–|--|-)\s*(?:19|20)\d\d(?!\d)"
# A dash between two numbers marks pages, unless the numbers are parts of a date or of a version.
DASH_PAGES = rf"(?<![\d.-])(?!{YEARS})\d+\s*(?:–|--)\s*\d+(?![\d-]|\.\d)"
# A hyphen marks pages only between two whole numbers that stand after a comma, a bracket, or the colon of a volume
# and end a field, as in 26(3), 1-34 (2021), since a date, an ISBN, and an identifier hold a hyphen too.
HYPHEN_PAGES = rf"(?:,\s+|\)\s*|(?<=[\d)]):\s*)(?!{YEARS})[1-9]\d*-[1-9]\d*(?=\s*(?:[.,;(]|$))"
# Marks that only a published article or a paper bears: the word proceedings or transactions, a volume, an article
# number, or pages.
PUBLISHED = re.compile(
    rf"\b(?:proceedings|proc|transactions|trans|vol|pp)\b|\barticle\s+\d|{DASH_PAGES}|{HYPHEN_PAGES}", re.IGNORECASE)
# Words and marks of a reference to an article or a paper, which a bibliographic database should hold: the marks
# above, a DOI, or the name of an event, a periodical, or a preprint server, which a talk or a news item also bears.
SCHOLARLY = re.compile(
    rf"{PUBLISHED.pattern}|\b(?:conference|conf|symposium|symp|workshop|journal|letters|magazine|arxiv|corr|"
    r"preprint)\b|10\.\d{4,9}/", re.IGNORECASE)
# An entry that goes on after its title with in and one word of two capital letters or more gives the short name of
# its venue, as in ICSE, 2021 or In: ASE (2021), also with a year, as In ICSE ’21.
SHORT_VENUE = re.compile(
    r"\W*[Ii]n:?\s+[A-Z][A-Za-z&/-]*[A-Z][A-Za-z]*(?:\s?['’‘]\s?\d\d|\s+(?:19|20)\d\d)?\s*(?:[,.(]|$)")
# Marks of a work that the databases often lack although its entry gives a venue, pages, or a DOI: a book, a standard,
# a thesis, a report, an upload to a repository, a blog post, or a talk, which IEEE style cites as presented at.
UNLISTED = re.compile(
    r"\b(?:\d+(?:st|nd|rd|th)|first|second|third|fourth|fifth|revised|new)\s+ed(?:ition|\.)(?!\s+of\b)|"
    r"\bch(?:ap(?:ter)?)?\.?\s*\d|\bstd\b|\bstandard\s+\d|(?-i:\bISO\b)|\brfc\s*\d|\bthesis\b|\bdissertation\b|"
    r"\btech(?:nical)?\.?\s+rep(?:ort|\.)|\bzenodo\b|\bfigshare\b|\bdryad\b|\bdataverse\b|\bsoftware\s+heritage\b|"
    r"\bpresented\s+at\b|\bkeynote\b|\binvited\s+talk\b|\btalk\s+at\b|\bblog\b", re.IGNORECASE)
# An entry by Anonymous, or with its authors or its details left out, names a work that the authors hide for the
# review. Anon before a capital letter is the given name of an author.
HIDDEN = r"(?:omitted|anonymi[sz]ed|blinded|removed|hidden|redacted|withheld|suppressed)"
HIDDEN_ENTRY = re.compile(
    rf"^\W*(?:anonym\w*|anon(?!\s+(?-i:[A-Z]))|blinded|self-(?:reference|citation)s?)\b|"
    rf"^\W*under\s+(?:double[-\s]?)?blind\s+review|"
    rf"^\W*(?:authors?(?:\(s\))?|names?)[’']?(?:\s+[\w-]+,?){{0,2}}\s+{HIDDEN}\b|"
    rf"\b{HIDDEN}\s+(?:for|due\s+to|because\s+of|to\s+(?:preserve|keep|ensure|maintain))\s+(?:[\w-]+\s+){{0,3}}"
    rf"(?:review\w*|submission|anonymity|blind\w*)|"
    rf"[\[(](?:anonymi[sz]ed|blinded|redacted)\b[^\])]*[\])]|[\[(][^\])]*(?<![\w-]){HIDDEN}[\])]",
    re.IGNORECASE)
# Outside the title, a sentence that ends in one of these words is a note of the authors on what they left out.
HIDDEN_NOTE = re.compile(rf"\b{HIDDEN}\s*(?:\.|$)", re.IGNORECASE)
# A year on its own, never a part of a DOI or of an arXiv ID.
YEAR = re.compile(r"(?<![\d./])(?:19|20)\d\d(?!\d|\.\d)")
LINE_END_WORD = re.compile(r"([a-z]+)- ([a-z]+)")
# No online source gets a title of fewer words, since many works share a short title. Hallucinator passes over
# such a title unless its entry gives an identifier.
MIN_TITLE_WORDS = 4
# The search asks for the records that hold two of the rarest words of a title or of an entry and passes over a word
# that this many titles hold. An entry adds names and short words of a venue, which are rarer than a word of a title.
TITLE_WORDS, COMMON_TITLE_WORD = 6, 1_000_000
ENTRY_WORDS, COMMON_ENTRY_WORD = 16, 50_000
CANDIDATES = 50
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
    query_cache: Path
    index_cache: Path
    timeout: float


@dataclass(frozen=True)
class Reference:
    """One reference of the JSON report of Hallucinator with what the lookups add.

    The status is verified, not_found, mismatch, or skipped. answered holds the sources that looked the reference
    up, and failed the core sources and the registries that did not answer for it. A mismatch names the source, the
    authors, and the address of a record under the title of the reference. other_title is the title of another work
    under the DOI or the arXiv ID of the reference. registered marks a DOI that exists without a record that
    PeerCheck reads. passed_over marks a reference that CrossRef did not get, since the online run passed it over."""

    number: int
    title: str
    text: str
    status: str
    answered: tuple[str, ...] = ()
    failed: tuple[str, ...] = ()
    authors: tuple[str, ...] = ()
    record_source: str = ""
    record_authors: tuple[str, ...] = ()
    record_url: str = ""
    dois: tuple[str, ...] = ()
    arxiv_id: str = ""
    other_title: str = ""
    registered: bool = False
    passed_over: bool = False


def check_batch(papers: list[Paper], profile: Profile, workdir: Path) -> dict[int, list[Finding]]:
    """Look up the references of every submission and return the findings of each paper.

    Each paper goes through the local databases first, several papers at a time. The online lookups then take the
    references of all papers that the local databases leave open."""
    settings = settings_from(profile.options("references"))
    folder = workdir / "references"
    folder.mkdir(parents=True, exist_ok=True)
    # PyMuPDF is not safe in several threads, therefore one thread reads and writes the list of every paper.
    sources = [_list_pdf(paper, folder) for paper in papers]
    with concurrent.futures.ThreadPoolExecutor(max_workers=LOCAL_RUNS) as pool:
        local = list(pool.map(lambda paper, source: _local_lookups(settings, paper, source, folder), papers, sources))
    refs = {paper.paper_id: found for paper, (found, _error) in zip(papers, local)}
    places = [(paper_id, index) for paper_id, found in refs.items() for index, ref in enumerate(found)
              if settings.online and _is_open(ref)]
    if places:
        total = sum(map(len, refs.values()))
        print(f"Asking the online sources about {len(places)} of {total} references.", file=sys.stderr)
    answers, failures = _online_lookups(settings, [refs[paper_id][index] for paper_id, index in places], folder)
    for (paper_id, index), answer in zip(places, answers):
        refs[paper_id][index] = answer
    if not os.environ.get("OPENALEX_KEY") and any("OpenAlex" in answer.failed for answer in answers):
        print(OPENALEX_KEY_NOTE, file=sys.stderr)
    failed_run = {places[place][0]: failure for place, failure in failures.items()}
    findings = {}
    for paper, (_found, error) in zip(papers, local):
        found = refs[paper.paper_id]
        findings[paper.paper_id] = [error] if error else _findings(found, settings) if found else [
            Finding("references.error", Severity.WARNING, "No reference list was found in the PDF")]
        if paper.paper_id in failed_run:
            findings[paper.paper_id].append(failed_run[paper.paper_id])
    return findings


def _local_lookups(settings: Settings, paper: Paper, source: Path,
                   folder: Path) -> tuple[list[Reference], Finding | None]:
    """Return the references of one paper after the lookups in the local databases, or the finding of a failed run."""
    try:
        refs = [_asked(ref, "DBLP") for ref in _local_run(settings, source, folder, f"paper-{paper.paper_id}")]
        return _confirmed_in_dblp(refs, settings.offline["DBLP"]), None
    except RUN_ERRORS as exc:
        return [], Finding("references.error", Severity.WARNING, f"The reference check did not run: {exc}")


def _list_pdf(paper: Paper, folder: Path) -> Path:
    """Write the reference list of a paper as a PDF with one line per entry and return its path, or the path of the
    paper itself when PeerCheck reads no list from it.

    Hallucinator ends a reference list at a line that starts like the heading of an appendix, such as a line of an
    entry that opens with the word Supplementary. With one line per entry, every line opens with its label."""
    entries = reference_list.read(paper.pdf)
    if not entries:
        return paper.pdf
    target = folder / f"paper-{paper.paper_id}-list.pdf"
    font = pymupdf.Font("cjk")
    rows = ["Reference list", "References", *(f"[{entry.number}] {_printable(entry.text)}" for entry in entries)]
    width = max(font.text_length(row, fontsize=LIST_FONT_SIZE) for row in rows) + 2 * LIST_MARGIN
    with pymupdf.open() as document:
        page = document.new_page(width=width, height=LIST_LEADING * len(rows) + 2 * LIST_MARGIN)
        writer = pymupdf.TextWriter(page.rect)
        for index, row in enumerate(rows, start=1):
            writer.append((LIST_MARGIN, LIST_MARGIN + LIST_LEADING * index), row, font=font, fontsize=LIST_FONT_SIZE)
        writer.write_text(page)
        document.subset_fonts()
        document.save(target, garbage=3, deflate=True)
    return target


def _printable(text: str) -> str:
    """Return a text that Hallucinator reads back from the list PDF as written: each letter in its plain form, no
    mark without a width, and a space for a character that the font of the list lacks."""
    return "".join(
        "" if unicodedata.category(letter) == "Cf" else
        " " if unicodedata.category(letter)[0] == "C" or letter == "�" or ord(letter) > 0xFFFF else letter
        for letter in unicodedata.normalize("NFKC", text))


def settings_from(options: dict) -> Settings:
    """Resolve the options of a profile against the cache and the defaults."""
    cache = Path(options.get("cache") or tools.cache_dir()).expanduser()
    tool = cache / "hallucinator"
    offline = {"DBLP": tool / "dblp.db"}
    for source, _flag, key in OFFLINE_DATABASES:
        if options.get(key):
            offline[source] = Path(options[key]).expanduser()
    online, online_titles = (_switch(options, name) for name in ("online", "online_titles"))
    return Settings(
        online=online,
        online_titles=online and online_titles,
        binary=Path(options.get("binary") or reference_setup.binary_path(cache)).expanduser(),
        offline=offline,
        local_corpus=Path(options["local_corpus"]).expanduser() if options.get("local_corpus") else None,
        retraction_csv=Path(options.get("retraction_csv") or cache / "retraction_watch.csv").expanduser(),
        query_cache=tool / "online-lookups.db",
        index_cache=tool / "index-lookups.json",
        timeout=float(options.get("timeout", 600)),
    )


def _switch(options: dict, name: str) -> bool:
    """Return an option that turns lookups on or off. Any other value than true or false is an error of the template,
    since the word false in quotes would turn the lookups on."""
    value = options.get(name, True)
    if not isinstance(value, bool):
        raise ProfileError(f"references.{name} must be true or false, not {value!r}")
    return value


def _local_run(settings: Settings, source: Path, folder: Path, stem: str) -> list[Reference]:
    """Run Hallucinator on a PDF with the local databases alone, with every online source off."""
    arguments = ["--disable-dbs", ",".join(name for name in ONLINE_SOURCES if name not in settings.offline)]
    for name, flag, _key in OFFLINE_DATABASES:
        if name in settings.offline:
            if not settings.offline[name].is_file():
                raise tools.ToolError(f"the offline {name} database is missing at {settings.offline[name]}; "
                                      "run peercheck --setup")
            arguments += [flag, str(settings.offline[name])]
    if settings.local_corpus:
        arguments += ["--local-corpus", str(settings.local_corpus)]
    found = _run(settings, arguments, source, folder, stem, settings.timeout, online=False)
    return [dataclasses.replace(ref, status="skipped") if _is_hidden(ref) and ref.status != "verified" else ref
            for ref in found]


def _online_run(settings: Settings, pending: list[Reference], folder: Path) -> list[Reference | None]:
    """Look up articles and papers of all submissions in one online run of Hallucinator and return each answer, if
    any.

    The run keeps the answers of its sources in the cache, a found work for seven days and a missing one for a day."""
    bib = folder / "online.bib"
    bib.write_text("".join(_bib_entry(key, ref) for key, ref in enumerate(pending, 1)), encoding="utf-8")
    off = [name for name in ONLINE_SOURCES if name in settings.offline or name not in RUN_SOURCES]
    arguments = ["--disable-dbs", ",".join(off), "--cache-path", str(settings.query_cache)]
    timeout = settings.timeout + ONLINE_SECONDS * len(pending)
    found = _run(settings, arguments, bib, folder, "online", timeout, online=True)
    answers = {answer.number: answer for answer in found}
    return [answer if answer and _is_answer_to(ref, answer) else None
            for ref, answer in zip(pending, map(answers.get, range(1, len(pending) + 1)))]


def _is_answer_to(ref: Reference, answer: Reference) -> bool:
    """Tell whether an answer of the online run under the number of a reference is an answer to it.

    The .bib reader of Hallucinator numbers the entries that it could parse, therefore an answer counts only under
    nearly the title sent. An entry that the reader passed over comes back without the title that was sent."""
    return answer.status == "skipped" or reference_match.near(ref.title, answer.title)


def _run(settings: Settings, arguments: list[str], source: Path, folder: Path, stem: str, timeout: float,
         online: bool) -> list[Reference]:
    """Run the CLI on a PDF or a .bib file and return its references, or [] if it read none."""
    if not settings.binary.is_file():
        raise tools.ToolError(f"Hallucinator is not installed at {settings.binary}; run peercheck --setup")
    report, log = folder / f"{stem}.json", folder / f"{stem}.log"
    report.unlink(missing_ok=True)
    config = folder / "hallucinator.toml"
    # An empty configuration file keeps a user's own Hallucinator settings, such as a web search, out of the run.
    config.write_text("", encoding="utf-8")
    command = [str(settings.binary), "check", "--config", str(config), "--no-color", "--no-searxng",
               "--json", str(report), "--output", str(log), *arguments, str(source)]
    try:
        done = subprocess.run(command, check=False, cwd=folder, env=_environment(folder, online),
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise tools.ToolError(f"Hallucinator did not finish within {timeout:g} seconds") from exc
    if done.returncode != 0:
        lines = [line.strip() for line in done.stderr.splitlines() if line.strip()]
        message = lines[-1] if lines else f"Hallucinator stopped with exit code {done.returncode}"
        if STALE_DATABASE.search(message):
            message = "an offline database of Hallucinator is empty or out of date; run peercheck --setup --refresh"
        raise tools.ToolError(message)
    if not report.is_file():
        return []
    return parse_report(json.loads(report.read_text(encoding="utf-8")))


def _confirmed_in_dblp(refs: list[Reference], database: Path) -> list[Reference]:
    """Compare each open reference with the DBLP records whose title its entry holds.

    Hallucinator looks up the title that it reads from an entry. Where it reads the title wrongly, such as with a
    part of the venue after a title that ends in a question mark, the lookup fails although DBLP holds the work."""
    if not any(_is_open(ref) for ref in refs):
        return refs
    try:
        with contextlib.closing(sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)) as records:
            records.execute("create virtual table temp.vocabulary using fts5vocab(main, publications_fts, row)")
            counts: dict[str, int] = {}
            return [_in_dblp(ref, records, counts) if _is_open(ref) else ref for ref in refs]
    except sqlite3.Error:
        return refs


def _in_dblp(ref: Reference, records: sqlite3.Connection, counts: dict[str, int]) -> Reference:
    """Return a reference after the comparison with the DBLP records that share rare words with it.

    The words come from the title that Hallucinator read. Where no record with these words bears the title, as for
    a title read from another part of the entry, the words come from the whole entry."""
    cited = _citation(ref)
    titles = _dblp_titles(reference_match.folded(ref.title), TITLE_WORDS, COMMON_TITLE_WORD, records, counts)
    if not any(cited.bears(title) for _record, title in titles):
        titles += _dblp_titles(cited.entry, ENTRY_WORDS, COMMON_ENTRY_WORD, records, counts)
    # The DBLP lookup of Hallucinator accepts a title from a ratio of 0.90, also the title of another work.
    if ref.status == "mismatch" and ref.record_source == "DBLP":
        titles += records.execute("select id, title from publications where key = ?",
                                  (ref.record_url.removeprefix(DBLP_RECORD_URL),)).fetchall()
        ref = dataclasses.replace(ref, status="not_found", record_source="", record_authors=(), record_url="")
    found = [(title, tuple(name for (name,) in records.execute(
        "select a.name from publication_authors l join authors a on a.id = l.author_id where l.pub_id = ?", (record,))))
        for record, title in dict.fromkeys(titles) if cited.bears(title)]
    return _compared(ref, cited, found, "DBLP")


def _dblp_titles(text: str, most: int, common: int, records: sqlite3.Connection,
                 counts: dict[str, int]) -> list[tuple[int, str]]:
    """Return the DBLP records that hold two of the rarest words of a folded text, each with its title.

    counts keeps the number of titles that hold each word, since the count of a common word takes long."""
    words = set(reference_match.WORD.findall(text)) | {first + second for first, second in LINE_END_WORD.findall(text)}
    words = {word for word in words if len(word) > 2 and not word.isdigit()}
    for word in words - counts.keys():
        row = records.execute("select doc from temp.vocabulary where term = ?", (word,)).fetchone()
        counts[word] = row[0] if row else 0
    rare = sorted((word for word in words if 0 < counts[word] < common), key=lambda word: (counts[word], word))[:most]
    if not rare:
        return []
    groups = (" AND ".join(f'"{word}"' for word in group) for group in itertools.combinations(rare, min(2, len(rare))))
    return records.execute(
        "select p.id, p.title from publications_fts join publications p on p.id = publications_fts.rowid "
        f"where publications_fts match ? order by rank limit {CANDIDATES}",
        (" OR ".join(f"({group})" for group in groups),)).fetchall()


def _citation(ref: Reference) -> Citation:
    return Citation(ref.text, ref.title, ref.authors)


def _compared(ref: Reference, cited: Citation, records: list[tuple[str, tuple[str, ...]]], source: str) -> Reference:
    """Return a reference after the comparison with the records of a source that bear its title, each a title with
    its authors.

    A record of the cited authors confirms the reference. Otherwise a record of other authors under nearly the title
    that Hallucinator read leaves a mismatch. A record without an author to compare confirms the reference when it
    bears nearly that whole title and no record names other authors, since many works share the part of a title
    before its colon."""
    named = [(title, authors) for title, authors in records if reference_match.compared_authors(authors)]
    if any(cited.same_authors(authors, title) for title, authors in named):
        return dataclasses.replace(ref, status="verified")
    if ref.status == "mismatch":
        return ref
    other = next((authors for title, authors in named if reference_match.near(cited.title, title)), None)
    if other:
        return dataclasses.replace(ref, status="mismatch", record_source=source, record_authors=tuple(other))
    whole = any(reference_match.near(cited.title, title) for title, _authors in records)
    return dataclasses.replace(ref, status="verified") if whole and not named else ref


def parse_report(data: list) -> list[Reference]:
    """Turn the JSON report of one file into references, in the order of the reference list."""
    entries = data[0].get("references", []) if data else []
    return sorted((_reference(entry, place) for place, entry in enumerate(entries, 1)), key=lambda ref: ref.number)


def _reference(entry: dict, place: int) -> Reference:
    """Return one reference of a report under the statuses of PeerCheck.

    Hallucinator 0.2.4 accepts a record once it names one cited author. Where the entry lists more authors than the
    record, it reports other authors once three cited authors are missing from a DBLP record, or one from a record
    of another source. It passes over a reference that the local databases lack and that gives a web address
    outside the sites of publishers. PeerCheck compares the authors of each record itself and looks up an article
    or a paper with such an address."""
    text = entry.get("raw_citation") or ""
    doi_info, arxiv_info = entry.get("doi_info") or {}, entry.get("arxiv_info") or {}
    dois = dict.fromkeys(d for d in [doi_info.get("doi", "")] + _dois(text) if retraction_watch.normalize_doi(d))
    arxiv = ARXIV_IN_TEXT.search(ARXIV_EXTRA.sub(r"\1", text))
    results = entry.get("db_results") or []
    ref = Reference(
        number=int(entry.get("original_number") or place),
        title=entry.get("title") or "",
        text=text,
        status=entry.get("status") or "",
        answered=tuple(dict.fromkeys(r["db"] for r in results if r.get("status") in ANSWERED)),
        failed=tuple(name for name in entry.get("failed_dbs") or () if name in CORE_SOURCES),
        authors=tuple(entry.get("ref_authors") or ()),
        dois=tuple(dois),
        arxiv_id=arxiv_info.get("arxiv_id") or (arxiv.group(1) if arxiv else ""),
    )
    cited, found = _citation(ref), tuple(entry.get("found_authors") or ())
    under_title = ref.status in ("verified", "mismatch")
    if under_title and not cited.same_authors(found):
        return dataclasses.replace(ref, status="mismatch", record_source=entry.get("source") or "",
                                   record_authors=found, record_url=entry.get("paper_url") or "")
    if under_title or any(cited.same_authors(authors) for authors in _set_aside(results)):
        return dataclasses.replace(ref, status="verified")
    looked_up = (ref.status in ("not_found", "inconclusive")
                 or (entry.get("url_check_skipped") and _is_published(ref)))
    return dataclasses.replace(ref, status="not_found" if looked_up else "skipped")


def _set_aside(results: list[dict]) -> list[list[str]]:
    """Return the authors of each record that a source holds under the title and that Hallucinator set aside for
    its authors, where the record names an author to compare.

    Hallucinator 0.2.4 reports no mismatch for a title of fewer than six words, and none for a record of CrossRef
    or PubMed that shares no family name with the entry."""
    return [result["authors"] for result in results if result.get("status") == "author_mismatch"
            and reference_match.compared_authors(result.get("authors") or ())]


def _asked(ref: Reference, source: str) -> Reference:
    """Return an open reference with a core source among the failed ones, unless the source answered for it."""
    if not _is_open(ref) or source not in CORE_SOURCES or source in (*ref.answered, *ref.failed):
        return ref
    return dataclasses.replace(ref, failed=(*ref.failed, source))


def _is_open(ref: Reference) -> bool:
    """Tell whether another source can still confirm a reference."""
    return ref.status in OPEN


def _is_hidden(ref: Reference) -> bool:
    """Tell whether the entry of a reference hides a work for the review, which no source gets."""
    return bool(HIDDEN_ENTRY.search(ref.text) or HIDDEN_NOTE.search(_beside_title(ref)))


def _is_recent(ref: Reference) -> bool:
    """Tell whether the newest year of an entry is this year or the year before, or whether it names no year."""
    years = [int(year) for year in YEAR.findall(ref.text)]
    return not years or max(years) >= datetime.date.today().year - 1


def _is_article(ref: Reference) -> bool:
    """Tell whether a reference names an article or a paper under a title that is long enough to look up.

    Its entry bears a mark of a venue, a volume, pages, or an identifier and, outside its title, no mark of a book, a
    standard, a thesis, a report, an upload to a repository, a talk, or a blog post."""
    if not _has_long_title(ref):
        return False
    before, after = _around_title(ref)
    scholarly = SCHOLARLY.search(ref.text) or SHORT_VENUE.match(after)
    return bool(scholarly) and not UNLISTED.search(f"{before} {after}")


def _has_long_title(ref: Reference) -> bool:
    """Tell whether the title of a reference is long enough to look up."""
    return len(ref.title.split()) >= MIN_TITLE_WORDS


def _is_published(ref: Reference) -> bool:
    """Tell whether a reference names an article or a paper by a mark that a talk or a news item lacks: an
    identifier or, outside its title, a mark of a published work."""
    return _is_article(ref) and bool(ref.dois or ref.arxiv_id or PUBLISHED.search(_beside_title(ref)))


def _beside_title(ref: Reference) -> str:
    """Return the entry of a reference without its title."""
    return " ".join(_around_title(ref))


def _around_title(ref: Reference) -> tuple[str, str]:
    """Return the entry of a reference before and after its title, or the whole entry and nothing when the entry
    does not hold the title. Only the letters and the digits of the title count, since a line end may cut a word
    of the title in the entry."""
    places = [place for place, letter in enumerate(ref.text) if letter.isalnum()]
    wanted = "".join(filter(str.isalnum, ref.title))
    start = "".join(ref.text[place] for place in places).find(wanted) if wanted else -1
    if start < 0:
        return ref.text, ""
    return ref.text[:places[start]], ref.text[places[start + len(wanted) - 1] + 1:]


def _is_reported(ref: Reference) -> bool:
    """Tell whether the check would report a reference, which is an open article or paper."""
    return _is_open(ref) and _is_article(ref)


def _online_lookups(settings: Settings, pending: list[Reference],
                    folder: Path) -> tuple[list[Reference], dict[int, Finding]]:
    """Return the open references of all papers after the online lookups, and the finding of an online run that
    failed by the place of each reference that was in it.

    DataCite, Crossref, and doi.org first answer for the DOIs and the arXiv IDs. With title lookups, one run of
    Hallucinator then asks its online sources for the articles and the papers, and DataCite gets each title that
    stays open. OpenAlex gets each article or paper that the check would otherwise report, and OpenReview those
    among them of the last two years, since it answers few requests and a database lists the papers of a venue some
    months after the venue."""
    if not pending:
        return [], {}
    refs = _confirmed_by_identifier(pending)
    if not settings.online_titles:
        return refs, {}
    sent = [index for index, ref in enumerate(refs) if _is_reported(ref)]
    failures = {}
    try:
        answers = _online_run(settings, [refs[index] for index in sent], folder) if sent else []
    except RUN_ERRORS as exc:
        failure = Finding("references.error", Severity.WARNING, f"The online lookups did not finish: {exc}")
        failures = dict.fromkeys(sent, failure)
        answers = [None] * len(sent)
    for index, answer in zip(sent, answers):
        refs[index] = _with_answer(refs[index], answer)
    kept = LookupCache(settings.index_cache)
    refs = _confirmed_by_title(refs, open_indexes.datacite_works, "DataCite",
                               lambda ref: _is_open(ref) and _has_long_title(ref), kept)
    refs = _confirmed_by_title(refs, open_indexes.openalex_works, "OpenAlex", _is_reported, kept, halves=True)
    refs = _confirmed_by_title(refs, open_indexes.openreview_works, "OpenReview",
                               lambda ref: _is_reported(ref) and _is_recent(ref), kept)
    kept.save()
    return refs, failures


def _confirmed_by_identifier(refs: list[Reference]) -> list[Reference]:
    """Compare each reference with the records of its DOIs and its arXiv ID in DataCite and Crossref."""
    dois = [[open_indexes.ARXIV_DOI + open_indexes.ARXIV_VERSION.sub("", ref.arxiv_id).lower()] * bool(ref.arxiv_id)
            + [doi.lower() for doi in ref.dois] for ref in refs]
    works, failed, unread = _registry_records(sorted({doi for found in dois for doi in found}))
    return [_identified(ref, found, works, failed, unread) if found else ref for ref, found in zip(refs, dois)]


def _registry_records(dois: list[str]) -> tuple[dict[str, tuple[open_indexes.Work, str]], dict[str, tuple[str, ...]],
                                                 set[str]]:
    """Ask DataCite, Crossref, and doi.org about DOIs, each one about the DOIs that the one before it lacks.

    Returns the record of each DOI with its source, the sources that did not answer for a DOI without a record, and
    the DOIs that exist without a record that PeerCheck reads, such as a DOI of another registration agency."""
    datacite, no_datacite = _registry_answer(open_indexes.datacite_doi_works, dois)
    # DataCite holds a record of every arXiv preprint.
    rest = [doi for doi in dois if doi not in datacite and not doi.startswith(open_indexes.ARXIV_DOI)]
    crossref, no_crossref = _registry_answer(open_indexes.crossref_doi_works, rest)
    agencies, no_agency = _registry_answer(open_indexes.doi_agencies, [doi for doi in rest if doi not in crossref])
    works = {doi: (work, source) for source, found in (("CrossRef", crossref), ("DataCite", datacite))
             for doi, work in found.items()}
    down = {"DataCite": no_datacite, "CrossRef": no_crossref, "doi.org": no_agency}
    failed, unread = {}, set()
    for doi in dois:
        registry = REGISTRIES.get(agencies.get(doi))
        if doi in works:
            continue
        if doi in agencies and (registry is None or doi not in down[registry]):
            unread.add(doi)
        elif doi in agencies:
            failed[doi] = (registry,)
        elif doi in no_agency or doi.startswith(open_indexes.ARXIV_DOI):
            # A DOI that doi.org does not know exists nowhere, whichever registry did not answer for it.
            failed[doi] = tuple(name for name, unanswered in down.items() if doi in unanswered)
    return works, {doi: names for doi, names in failed.items() if names}, unread


def _registry_answer(lookup, dois: list[str]) -> tuple[dict, set[str]]:
    """Return what a registry holds on DOIs, 50 per request, and the DOIs of the requests that it did not answer."""
    found, unanswered, failures = {}, set(), 0
    for first in range(0, len(dois), open_indexes.BATCH):
        batch = dois[first:first + open_indexes.BATCH]
        answer = _answer(lookup, batch) if failures < MOST_FAILURES else None
        failures = failures + 1 if answer is None else 0
        if answer is None:
            unanswered.update(batch)
        else:
            found.update(answer)
    return found, unanswered


def _answer(lookup, question):
    """Return the answer of a registry or an open index, or None when it did not answer."""
    try:
        return lookup(question)
    except open_indexes.LOOKUP_ERRORS:
        return None


def _identified(ref: Reference, dois: list[str], works: dict, failed: dict, unread: set[str]) -> Reference:
    """Return a reference after the comparison with the records of its DOIs and its arXiv ID.

    The cited work confirms the reference, and so does a record under its title without an author to compare. A
    record under its title that names other authors leaves a mismatch, unless an earlier source left one. Another
    work goes into the report. A record without a title or under a title in another script gives nothing to
    compare, therefore its DOI counts as registered."""
    cited = _citation(ref)
    records = [works[doi] for doi in dois if doi in works]
    kinds = [_record_kind(cited, work) for work, _source in records]
    if CITED_WORK in kinds or (NO_AUTHOR in kinds and OTHER_AUTHORS not in kinds):
        return dataclasses.replace(ref, status="verified")
    apart = [work.title for (work, _source), kind in zip(records, kinds) if kind == OTHER_WORK]
    answered = [source for _work, source in records]
    if any(doi.startswith(open_indexes.ARXIV_DOI) and doi not in works and doi not in failed for doi in dois):
        answered.append("DataCite")
    down = dict.fromkeys(name for doi in dois for name in failed.get(doi, ()) if name not in ref.failed)
    answer = dataclasses.replace(
        ref, answered=(*ref.answered, *answered), failed=(*ref.failed, *down),
        other_title=next((title for title in apart if title and reference_match.in_latin_letters(title)), ""),
        registered=bool(unread.intersection(dois)) or any(
            not title or not reference_match.in_latin_letters(title) for title in apart))
    if OTHER_AUTHORS not in kinds or ref.status == "mismatch":
        return answer
    work, source = records[kinds.index(OTHER_AUTHORS)]
    return dataclasses.replace(answer, status="mismatch", record_source=source, record_authors=work.authors)


def _record_kind(cited: Citation, work: open_indexes.Work) -> str:
    """Tell what the record of a DOI or an arXiv ID is to a reference.

    The cited work names the cited authors under the title or under a title that shares words with it, since a
    preprint may change its title from one version to the next. A record of a whole publication or without an
    author to compare stands under the title only when it bears nearly the whole title, since an entry holds the
    name of its journal as a field and many works share the part of a title before its colon. A record of the
    cited authors, of the volume, or of the journal is no other work."""
    named = bool(reference_match.compared_authors(work.authors))
    same = named and cited.same_authors(work.authors, work.title)
    whole = work.container or not named
    under = reference_match.near(cited.title, work.title) if whole else cited.bears(work.title)
    if same and (under or reference_match.share_words(cited.title, work.title)):
        return CITED_WORK
    if under:
        return OTHER_AUTHORS if named else NO_AUTHOR
    return NOTHING if same or work.container or cited.holds_words(work.title) else OTHER_WORK


def _confirmed_by_title(refs: list[Reference], works_of, source: str, wanted, kept: LookupCache,
                        halves: bool = False) -> list[Reference]:
    """Compare each wanted reference with the records that an open index holds under its title.

    The index gets a few requests at a time, and no further one once three in a row stay without an answer, such
    as beyond its daily budget, or once its seconds for the titles of the run are over. A kept answer still counts
    then. A reference that a core source did not answer counts as not looked up."""
    asked = [index for index, ref in enumerate(refs) if wanted(ref)]
    answers, failures, lookup = list(refs), 0, works_of
    budget = open_indexes.Budget(INDEX_SECONDS * len(asked))
    with concurrent.futures.ThreadPoolExecutor(max_workers=INDEX_RUNS) as pool:
        for first in range(0, len(asked), INDEX_RUNS):
            group = asked[first:first + INDEX_RUNS]
            if failures >= MOST_FAILURES or budget.is_spent():
                lookup = _no_request
            found = list(pool.map(
                lambda index, lookup=lookup: _index_answer(refs[index], lookup, source, kept, halves), group))
            for index, answer in zip(group, found):
                failures = failures + 1 if answer is None else 0
                answers[index] = answer or _asked(refs[index], source)
    return answers


def _no_request(title: str) -> list[open_indexes.Work]:
    """Stand in for an index that gets no further request in a run, which leaves each title to the kept answers."""
    raise OSError(f"no request for {title}")


def _index_answer(ref: Reference, works_of, source: str, kept: LookupCache, halves: bool) -> Reference | None:
    """Return a reference after the comparison with the records of an open index, or None when the index did not
    answer.

    The index gets the whole title. With halves, it then gets parts of the title, since one wrong letter in a
    title, such as a hyphen that a line end left, hides the record from a search for the whole title."""
    cited = _citation(ref)
    answer = dataclasses.replace(ref, answered=(*ref.answered, source))
    for query in (ref.title, *(_halves(ref.title) if halves else ())):
        try:
            works = kept.works(source, query, works_of)
        except open_indexes.LOOKUP_ERRORS:
            return None
        answer = _compared(answer, cited, [(work.title, work.authors) for work in works if cited.bears(work.title)],
                           source)
        if answer.status == "verified":
            break
    return answer


def _halves(title: str) -> list[str]:
    """Return the two halves of a title of eight words or more, or the first and the last four words of a title of
    five to seven words."""
    words = title.split()
    middle = len(words) // 2
    if middle >= MIN_TITLE_WORDS:
        return [" ".join(words[:middle]), " ".join(words[middle:])]
    if len(words) > MIN_TITLE_WORDS:
        return [" ".join(words[:MIN_TITLE_WORDS]), " ".join(words[-MIN_TITLE_WORDS:])]
    return []


def _with_answer(ref: Reference, answer: Reference | None) -> Reference:
    """Return a reference with the answer of the online run, whose core source is CrossRef.

    A run that failed or passed over the reference says nothing about it. A later run passes over the reference
    again, since its title is too short for the run. A record with other authors that an earlier source holds
    stays unless a source confirms the reference."""
    if answer is None or answer.status == "skipped":
        asked = _asked(ref, "CrossRef")
        return dataclasses.replace(asked, passed_over=answer is not None and asked.failed != ref.failed)
    merged = dataclasses.replace(ref, answered=ref.answered + answer.answered,
                                 failed=(*ref.failed, *(name for name in answer.failed if name not in ref.failed)))
    if answer.status == "verified" or (answer.status == "mismatch"
                                       and _citation(ref).same_authors(answer.record_authors)):
        return dataclasses.replace(merged, status="verified")
    if answer.status == "mismatch" and ref.status != "mismatch":
        merged = dataclasses.replace(merged, status="mismatch", record_source=answer.record_source,
                                     record_authors=answer.record_authors)
    return _asked(merged, "CrossRef")


def _bib_entry(key: int, ref: Reference) -> str:
    authors = " and ".join(name.translate(BIB_ESCAPES) for name in ref.authors)
    return f"@misc{{ref{key},\n  title = {{{ref.title.translate(BIB_ESCAPES)}}},\n  author = {{{authors}}},\n}}\n"


def _findings(refs: list[Reference], settings: Settings) -> list[Finding]:
    findings = [finding for ref in refs for finding in _lookup_findings(ref)]
    findings.extend(_notes(refs))
    findings.extend(_retraction_findings(refs, settings.retraction_csv))
    findings.append(_summary(refs, settings))
    return findings


def _lookup_findings(ref: Reference) -> list[Finding]:
    evidence = excerpt(ref.text, EVIDENCE_LIMIT)
    other = f'"{excerpt(ref.other_title, TITLE_LIMIT)}"'
    outcome = _outcome(ref)
    findings = []
    if outcome == "not found" and _is_warned(ref):
        hint = f". Its DOI or arXiv ID belongs to {other}" if ref.other_title else ""
        findings.append(Finding("references.not-found", Severity.WARNING,
                                f"{_label(ref)} was not found in {', '.join(dict.fromkeys(ref.answered))}{hint}",
                                evidence=evidence))
    if outcome == "conflict" and ref.other_title:
        findings.append(Finding("references.identifier-mismatch", Severity.WARNING,
                                f"{_label(ref)} gives the DOI or arXiv ID of another work, {other}", evidence=evidence))
    if _has_other_authors(ref):
        names = ", ".join(ref.record_authors[:NAMES_LIMIT]) + " et al." * (len(ref.record_authors) > NAMES_LIMIT)
        findings.append(Finding("references.author-mismatch", Severity.WARNING,
                                f"{_label(ref)} matches a title in {ref.record_source} whose authors differ: {names}",
                                evidence=evidence))
    return findings


def _label(ref: Reference) -> str:
    return f'Reference [{ref.number}] "{excerpt(ref.title, TITLE_LIMIT)}"'


def _outcome(ref: Reference) -> str:
    """Return the group of a reference in the summary: found, not found, conflict, or not looked up.

    A lookup that failed leaves a reference as not looked up, unless its identifier belongs to another work, since
    no other source changes whose work an identifier names."""
    if ref.status == "skipped":
        return "not looked up"
    if _has_other_work(ref) or _has_other_authors(ref):
        return "conflict"
    if ref.status == "verified":
        return "found"
    return "not looked up" if ref.failed else "not found"


def _has_other_work(ref: Reference) -> bool:
    """Tell whether the report names the work of the DOI or the arXiv ID of a reference in a finding of its own.

    The warning of an article or a paper that no source holds names that work itself. The record of a dataset, a
    software release, or a report often bears a title of its own, therefore only a title that shares no words with
    the cited one names another work."""
    if not ref.other_title:
        return False
    if ref.status == "verified":
        return True
    if _is_article(ref):
        return bool(ref.failed) or ref.status == "mismatch"
    return not reference_match.share_words(ref.title, ref.other_title)


def _has_other_authors(ref: Reference) -> bool:
    """Tell whether a record under the title of an article or a paper names other authors, once each core source
    and the registry of its DOI answered, since a source that did not answer may hold the cited work under the
    same title. DBLP lists other works under the title of a book, such as its reviews."""
    return ref.status == "mismatch" and not ref.failed and _is_article(ref)


def _is_warned(ref: Reference) -> bool:
    """Tell whether a reference not found calls for a warning: an article or a paper, unless its DOI exists."""
    return _is_article(ref) and not ref.registered


def _notes(refs: list[Reference]) -> list[Finding]:
    """Return the notes on the references that no database confirms and that call for no warning. The references
    whose lookup failed get one note for each set of sources that failed."""
    unconfirmed = [ref for ref in refs if _outcome(ref) == "not found" and not _is_warned(ref)]
    failed: dict[frozenset[str], list[Reference]] = {}
    passed_over = []
    for ref in refs:
        if _outcome(ref) != "not looked up":
            continue
        if ref.status == "skipped" or ref.passed_over:
            passed_over.append(ref)
        else:
            failed.setdefault(frozenset(ref.failed), []).append(ref)
    notes = (("references.unconfirmed", unconfirmed, UNCONFIRMED),
             *(("references.unchecked", listed, FAILED_LOOKUP.format(sources=", ".join(listed[0].failed)))
               for listed in failed.values()),
             ("references.unchecked", passed_over, PASSED_OVER))
    return [Finding(check_id, Severity.INFO, f"{_numbers(listed)} {reason}",
                    evidence=excerpt("; ".join(f"[{ref.number}] {ref.title}" for ref in listed), EVIDENCE_LIMIT))
            for check_id, listed, reason in notes if listed]


def _numbers(refs: list[Reference]) -> str:
    labels = [f"[{ref.number}]" for ref in refs]
    if len(labels) == 1:
        return f"Reference {labels[0]} was"
    return f"References {', '.join(labels[:-1])}{',' if len(labels) > 2 else ''} and {labels[-1]} were"


def _retraction_findings(refs: list[Reference], path: Path) -> list[Finding]:
    if not path.is_file():
        return [Finding("references.error", Severity.WARNING,
                        f"The Retraction Watch data is missing at {path}; run peercheck --setup")]
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
                    f"{_label(ref)} carries a Retraction Watch notice: {notice.nature} of {notice.date}",
                    evidence=excerpt(f"DOI {doi}. Reason: {notice.reason}", EVIDENCE_LIMIT),
                ))
                break
    return findings


def _summary(refs: list[Reference], settings: Settings) -> Finding:
    counts = collections.Counter(_outcome(ref) for ref in refs)
    mode = ("with online title lookups" if settings.online_titles
            else "with DOI and arXiv ID lookups" if settings.online else "offline")
    return Finding(
        "references.summary", Severity.INFO,
        f"{len(refs)} reference{'s' * (len(refs) != 1)} checked {mode}: {counts['found']} found, "
        f"{counts['not found']} not found, {counts['conflict']} with other authors or identifiers, "
        f"{counts['not looked up']} not looked up",
    )


def _dois(text: str) -> list[str]:
    found = []
    # The text with its breaks joined adds a DOI that a line end cut, and the text as it is keeps one that ends a
    # sentence before a number, such as a year.
    for raw in DOI_IN_TEXT.findall(text) + DOI_IN_TEXT.findall(DOI_BREAK.sub(r"\1", text)):
        doi = raw.rstrip(".;\"'”’")
        # A closing bracket belongs to the DOI only when the DOI also opens one, as in SICI DOIs.
        while doi and doi[-1] in ")]" and doi.count(doi[-1]) > doi.count("(" if doi[-1] == ")" else "["):
            doi = doi[:-1].rstrip(".;")
        found.append(doi)
    return found


def _environment(home: Path, online: bool) -> dict[str, str]:
    """Return a bare environment, which keeps the keys and the settings of the user away from a run. The online run
    alone gets the address for CrossRef and the proxies."""
    names = ("PATH", "SYSTEMROOT", "TEMP", "TMP", *(ONLINE_VARIABLES if online else ()))
    env = {name: os.environ[name] for name in names if os.environ.get(name)}
    env.update({"HOME": str(home), "LANG": "C.UTF-8"})
    return env

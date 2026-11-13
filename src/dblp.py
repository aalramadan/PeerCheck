"""Index of the dblp publications of a set of people, read offline from the dblp XML dump.

The dump (https://dblp.org/xml/dblp.xml.gz, CC0 1.0) is streamed with lxml iterparse, with the
character entities of dblp.dtd resolved. The index keeps, for each person of the input, the dblp
names that count as that person, and the publications (key, year, title, DOI, authors) under those
names.

A person matches dblp in one of three ways.

- A dblp person ID in Person.dblp, such as 12/3456 or https://dblp.org/pid/12/3456.html, selects
  the names of that person record exactly, after the crossref of a merged record.
- Otherwise the name selects the person records whose names fold to the same words once the dblp
  homonym suffix, such as " 0001", is removed, together with the records whose names share the
  first and the last word, such as Lionel C. Briand for Lionel Briand, since dblp may keep one
  person under both forms. The first and the last word are compared without a generational suffix,
  such as Jr. An umlaut also matches its ASCII spelling, such as Juergen Mueller for Jürgen Müller,
  while two plain names stay apart, such as Xue and Xu. A plain name that no person record holds
  also finds the other plain spelling of an umlaut, where ae, oe, ue, or aa stands before a
  consonant, such as Jorg for Joerg. Two names that both hold middle names name one person only
  where a middle name of one starts as one of the other does, which keeps Mona Reza Farid apart
  from Mona Amin Farid.
- When several person records match, or a dblp disambiguation page holds the name, the affiliation
  notes of each record are compared with Person.affiliation by the method of ISCA-2021-Script
  (github.com/hibagus/ISCA-2021-Script, filter_affiliation, fuzzy partial ratio of at least 80),
  with whole folded words in place of letters, a rapidfuzz token set ratio of at least 80, since a
  partial ratio lets ETH fit the word Netherlands. An affiliation of three letters or fewer, such as
  UW, picks no record. One surviving record resolves the name. Otherwise the identity is ambiguous
  and keeps the names of every matching record, with their number, for a person to check.

The dump is read twice, first for the person records and then for the publications under the names
of the matched records. Each read hands lxml only the records it may need, which it finds in the raw
bytes. A further read of the person records runs only for a merged record whose target came earlier
in the dump.
"""

from __future__ import annotations

import gzip
import json
import re
import unicodedata
from collections.abc import Callable, Collection, Iterable, Iterator
from dataclasses import dataclass, field
from itertools import product
from pathlib import Path
from typing import BinaryIO

from lxml import etree
from rapidfuzz import fuzz

from peercheck.models import Person

RECORDS = (
    "article", "inproceedings", "proceedings", "book", "incollection", "phdthesis", "mastersthesis", "www",
    "person", "data",
)
# The affiliation cutoff of filter_affiliation in ISCA-2021-Script.
AFFILIATION_MIN = 80
# Affiliations of at most this many letters, such as UW, may name several organizations.
SHORT_AFFILIATION = 3
MAX_SCANS = 3
# An index of version 1 resolved the names by other rules. It loads, and is built again.
INDEX_VERSION = 2
PEOPLE = ("www", "person")
# The start of the tags of people and of authors, cut to five bytes, the longest that CPython searches fast.
_PEOPLE_TAGS, _AUTHOR_TAG = (b"<www", b"<pers"), b"<auth"
_CHUNK = 1 << 17
_ATTRIBUTES = rb"""(?:\s+[\w:.-]+\s*=\s*(?:"[^"<]*"|'[^'<]*'))*\s*"""
_ROOT = re.compile(rb"<dblp" + _ATTRIBUTES + rb">")
_RECORD_END = re.compile(rb"</(?:" + "|".join(RECORDS).encode() + rb")\s*>")
_RAW_AUTHOR = re.compile(rb"<author" + _ATTRIBUTES + rb">([^<]*)</author\s*>")
_REFERENCE = re.compile(r"&([^;\x00]*);")
# Characters that no XML text holds: the first parts raw names, the second marks a reference of no known character.
_BREAK, _DOUBT = "\x00", "\x01"
_Spans = Callable[[bytes, int, int], list[tuple[int, int]]]
_HOMEPAGES = "homepages/"
_HOMONYM = re.compile(r"\s+\d{4}$")
_GENERATIONS = frozenset(["jr", "sr", "ii", "iii"])
# The ASCII spellings of the letters that fold to one letter, such as ue in Mueller.
_UMLAUTS = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "å": "aa", "ø": "oe", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue",
                          "Å": "Aa", "Ø": "Oe"})
# The second letter of ae, oe, ue, and aa before a consonant, where the two letters may spell an umlaut.
_DIGRAPH = re.compile(r"(?:(?<=[aou])e|(?<=a)a)(?=[b-df-hj-np-tv-z])")
_PID = re.compile(r"(?:^|^pid/|/pid/|homepages/)([a-z0-9]+/[A-Za-z0-9_-]+)$")
_WORD = re.compile(r"[a-z0-9]+")
_DOI = re.compile(r"(?:doi\.org/|^doi:)(10\.\d{4,9}/\S+)$", re.IGNORECASE)
_ARXIV = re.compile(r"arxiv\.org/abs/([a-z.-]+/\d{7}|\d{4}\.\d{4,5})", re.IGNORECASE)
# Letters that Unicode decomposition leaves as they are.
_SPECIAL = str.maketrans({
    "ø": "o", "Ø": "O", "ß": "ss", "æ": "ae", "Æ": "AE", "œ": "oe", "Œ": "OE", "ł": "l", "Ł": "L", "đ": "d",
    "Đ": "D", "ð": "d", "Ð": "D", "þ": "th", "Þ": "Th", "ı": "i",
})


@dataclass(frozen=True)
class Publication:
    """One dblp record with the fields that the checks of PeerCheck use."""

    key: str
    year: int | None
    title: str
    doi: str
    authors: tuple[str, ...]


@dataclass(frozen=True)
class Identity:
    """The dblp names that count as one person of the input, and how they were found."""

    names: tuple[str, ...] = ()
    pid: str = ""
    records: int = 0
    ambiguous: bool = False
    method: str = "no match"


@dataclass
class DblpIndex:
    """The publications of a set of people, keyed by dblp key, and the dblp identity of each person."""

    publications: dict[str, Publication] = field(default_factory=dict)
    identities: dict[str, Identity] = field(default_factory=dict)
    names: dict[str, list[str]] = field(default_factory=dict)
    source: str = ""
    version: int = INDEX_VERSION
    _by_name: dict[str, list[str]] = field(default_factory=dict, init=False, repr=False, compare=False)
    _by_doi: dict[str, str] = field(default_factory=dict, init=False, repr=False, compare=False)

    def identity(self, person: Person) -> Identity | None:
        """Return the identity of a person by key, or else the identity of the only input of that name."""
        found = self.identities.get(person_key(person))
        if found is not None:
            return found
        keys = self.names.get(fold(person.name), [])
        candidates = {self.identities[key] for key in keys}
        return candidates.pop() if len(candidates) == 1 else None

    def publications_of(self, person: Person, since: int | None = None) -> list[Publication]:
        """Return the publications under the dblp names of a person, from a year on if one is given."""
        identity = self.identity(person)
        if identity is None:
            return []
        if not self._by_name:
            for publication in self.publications.values():
                for author in publication.authors:
                    self._by_name.setdefault(author, []).append(publication.key)
        keys = sorted({key for name in identity.names for key in self._by_name.get(name, ())})
        found = [self.publications[key] for key in keys]
        return [p for p in found if since is None or (p.year is not None and p.year >= since)]

    def find_doi(self, doi: str) -> Publication | None:
        """Return the indexed publication with a DOI, compared without case, or None."""
        if not self._by_doi:
            self._by_doi = {p.doi: p.key for p in self.publications.values() if p.doi}
        key = self._by_doi.get(doi.strip().lower())
        return self.publications[key] if key else None

    def missing(self, people: Iterable[Person]) -> list[Person]:
        """Return the people the index holds no identity for, who are all of them under an older format."""
        return [person for person in people if self.version != INDEX_VERSION or self.identity(person) is None]

    def save(self, path: Path) -> None:
        """Write the index to a gzip-compressed JSON file."""
        data = {
            "version": INDEX_VERSION,
            "source": self.source,
            "publications": [[p.key, p.year, p.title, p.doi, list(p.authors)] for p in self.publications.values()],
            "identities": {
                key: [list(i.names), i.pid, i.records, i.ambiguous, i.method] for key, i in self.identities.items()
            },
            "names": self.names,
        }
        with gzip.open(path, "wt", encoding="utf-8") as handle:
            json.dump(data, handle)


def load_index(path: Path) -> DblpIndex:
    """Read an index that DblpIndex.save wrote."""
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        data = json.load(handle)
    if data.get("version") not in (1, INDEX_VERSION):
        raise ValueError(f"{path} holds a dblp index of another version; build it again")
    return DblpIndex(
        publications={row[0]: Publication(row[0], row[1], row[2], row[3], tuple(row[4])) for row in data["publications"]},
        identities={
            key: Identity(tuple(names), pid, records, ambiguous, method)
            for key, (names, pid, records, ambiguous, method) in data["identities"].items()
        },
        names=data["names"],
        source=data["source"],
        version=data["version"],
    )


def files(cache: Path) -> tuple[Path, Path, Path]:
    """Return the dump, its DTD, and the saved co-author index in the cache of peercheck --setup and --conflicts."""
    folder = cache / "dblp"
    return folder / "dblp.xml.gz", folder / "dblp.dtd", folder / "coauthors.json.gz"


def build_index(dump: Path, people: Iterable[Person], dtd: Path | None = None) -> DblpIndex:
    """Scan the dblp dump and index the publications of the given people."""
    people = list({person_key(p): p for p in people}.values())
    scan = _Scan(dump, dtd or dump.with_name("dblp.dtd"))
    loose = {key for p in people for key in _umlaut_keys(p.name)} - {""}
    pids = {parse_pid(p.dblp) for p in people} - {""}
    for _ in range(MAX_SCANS):
        scan.read_people(loose, pids)
        identities = {person_key(p): _resolve(p, scan) for p in people}
        pids = {i.pid for i in identities.values() if i.method == "pid not found" and i.pid not in scan.pids}
        loose = set()
        if not pids:
            break
    scan.read_publications(frozenset(name for i in identities.values() for name in i.names))
    names: dict[str, list[str]] = {}
    for p in people:
        names.setdefault(fold(p.name), []).append(person_key(p))
    return DblpIndex(publications=scan.publications, identities=identities, names=names, source=str(dump))


def fold(text: str) -> str:
    """Return the words of a text in lowercase ASCII, joined by single spaces."""
    if not text.isascii():
        decomposed = unicodedata.normalize("NFKD", text.translate(_SPECIAL))
        # Accents drop out, while any other character outside ASCII, such as a dash, parts two words.
        text = "".join(c if c.isascii() else " " for c in decomposed if not unicodedata.combining(c))
    return " ".join(_WORD.findall(text.lower()))


def base_name(name: str) -> str:
    """Return a dblp name without its homonym suffix, such as Wei Wang for Wei Wang 0042."""
    return _HOMONYM.sub("", name.strip())


def loose_keys(name: str) -> tuple[str, ...]:
    """Return the first and the last word of a folded name without suffixes, in each spelling of its umlauts.

    Jürgen Müller gives jurgen muller, juergen muller, jurgen mueller, and juergen mueller, and a plain name one key.
    """
    base = base_name(name)
    first, _middle, last = _name_words(base)
    if base.isascii():
        return (f"{first} {last}".strip(),)
    spelled = _name_words(base.translate(_UMLAUTS))
    pairs = product((first, spelled[0]), (last, spelled[2]))
    return tuple(dict.fromkeys(f"{one} {other}".strip() for one, other in pairs))


def _umlaut_keys(name: str) -> tuple[str, ...]:
    """Return the loose keys of a name, then each with ae, oe, ue, and aa before a consonant as one letter."""
    keys = loose_keys(name)
    plain = tuple([_DIGRAPH.sub("", key) for key in keys])
    return keys if plain == keys else tuple(dict.fromkeys(keys + plain))


def parse_pid(text: str) -> str:
    """Return the dblp person ID of a pid, a homepages key, or a dblp person URL, or an empty string."""
    text = re.sub(r"\.(?:html|xml|bib|rss|nt|rdf|ttl)$", "", text.strip().rstrip("/"))
    match = _PID.search(text)
    return match.group(1) if match else ""


def _name_words(name: str) -> tuple[str, list[str], str]:
    """Return the first word, the middle words, and the last word of a folded name without a generational suffix."""
    words = fold(name).split()
    while len(words) > 1 and words[-1] in _GENERATIONS:
        words.pop()
    return (words[0] if words else ""), words[1:-1], (words[-1] if len(words) > 1 else "")


def person_key(person: Person) -> str:
    """Return the key of a person in the index, by dblp person ID or else by name and affiliation."""
    pid = parse_pid(person.dblp)
    return f"pid:{pid}" if pid else f"name:{fold(person.name)}|{fold(person.affiliation)}"


@dataclass(frozen=True)
class _Record:
    pid: str
    names: tuple[str, ...]
    affiliations: tuple[str, ...]
    disambiguation: bool


class _DtdResolver(etree.Resolver):
    def __init__(self, dtd: Path) -> None:
        super().__init__()
        self.dtd = str(dtd)

    def resolve(self, system_url, public_id, context):
        if system_url and system_url.endswith("dblp.dtd"):
            return self.resolve_filename(self.dtd, context)
        # Any other external entity reads as empty, so a crafted dump cannot pull in a local file.
        return self.resolve_string("", context)


class _Scan:
    """The publications and person records that the reads of one dump collected so far."""

    def __init__(self, dump: Path, dtd: Path) -> None:
        if not dump.is_file():
            raise FileNotFoundError(f"dblp dump not found: {dump}")
        if not dtd.is_file():
            raise FileNotFoundError(f"dblp.dtd not found: {dtd}; the dump needs it for its character entities")
        self.dump, self.dtd = dump, dtd
        self.publications: dict[str, Publication] = {}
        self.records: dict[str, _Record] = {}
        self.by_name: dict[str, list[str]] = {}
        self.by_loose: dict[str, list[str]] = {}
        self.redirects: dict[str, str] = {}
        self.pids: set[str] = set()
        self.entities = _entities(dtd)

    def read_people(self, loose: set[str], pids: set[str]) -> None:
        """Read the dump once and collect the person records that the names and person IDs select."""
        # Targets of merged records join the wanted IDs during the read, while only the IDs wanted from
        # the start count as covered, since a target may precede its merged record in the dump.
        wanted = set(pids)
        named = _name_spans(
            lambda names: {name for name in set(names) if not loose.isdisjoint(_umlaut_keys(name))}, self.entities,
        )

        def spans(data: bytes, start: int, end: int) -> list[tuple[int, int]]:
            if all(data.find(tag, start, end) < 0 for tag in _PEOPLE_TAGS):
                return []
            # A person ID selects by the key of a record, which only lxml reads.
            return [(start, end)] if pids else named(data, start, end)

        for element in self._elements(spans):
            if element.tag in PEOPLE:
                self._person(element, loose, wanted)
        self.pids |= pids

    def read_publications(self, names: frozenset[str]) -> None:
        """Read the dump once and collect the publications with an author under one of the dblp names."""
        for element in self._elements(_name_spans(names.intersection, self.entities)):
            if element.tag not in PEOPLE:
                self._publication(element, names)

    def _elements(self, spans: _Spans) -> Iterator[etree._Element]:
        opener = gzip.open if self.dump.suffix == ".gz" else open
        with opener(self.dump, "rb") as handle:
            events = etree.iterparse(
                _Selected(handle, spans), events=("end",), tag=RECORDS, load_dtd=True, resolve_entities=True,
                no_network=True, huge_tree=True,
            )
            events.resolvers.add(_DtdResolver(self.dtd))
            for _, element in events:
                yield element
                # Clearing each record and its finished siblings keeps the memory flat over the dump.
                element.clear()
                while element.getprevious() is not None:
                    del element.getparent()[0]

    def _publication(self, element, names: frozenset[str]) -> None:
        authors = tuple((child.text or "").strip() for child in element if child.tag == "author")
        key = element.get("key", "")
        if names.isdisjoint(authors) or key in self.publications:
            return
        year = (element.findtext("year") or "").strip()
        title = element.find("title")
        self.publications[key] = Publication(
            key=key,
            year=int(year) if year.isdigit() else None,
            title=_title(title),
            doi=_doi([child.text or "" for child in element if child.tag == "ee"]),
            authors=authors,
        )

    def _person(self, element, loose: set[str], pids: set[str]) -> None:
        key = element.get("key", "")
        if not key.startswith(_HOMEPAGES):
            return
        pid = key[len(_HOMEPAGES):]
        target = (element.findtext("crossref") or "").strip()
        if target.startswith(_HOMEPAGES):
            if pid in pids:
                self.redirects[pid] = target[len(_HOMEPAGES):]
                pids.add(self.redirects[pid])
            return
        names = tuple((child.text or "").strip() for child in element if child.tag == "author")
        if pid in self.records or not (pid in pids or any(not loose.isdisjoint(_umlaut_keys(name)) for name in names)):
            return
        self.records[pid] = _Record(
            pid=pid,
            names=names,
            affiliations=tuple(
                (note.text or "").strip() for note in element if note.tag == "note" and note.get("type") == "affiliation"
            ),
            disambiguation="disambiguation" in (element.get("publtype") or "").split(),
        )
        for name in names:
            self.by_name.setdefault(fold(base_name(name)), []).append(pid)
            for key in _umlaut_keys(name):
                self.by_loose.setdefault(key, []).append(pid)


class _Selected:
    """The dump as a file that holds only the records a test selects, so that lxml parses few records.

    A record ends at its end tag, which the raw bytes show while they hold no comment, CDATA section, or processing
    instruction. From the first of these on, and where the dump defines an entity of its own, it passes unchanged.
    """

    def __init__(self, handle: BinaryIO, spans: _Spans) -> None:
        self.parts = self._parts(handle, spans)

    def read(self, _size: int = -1) -> bytes:
        """Return the next bytes that are left of the dump, empty at its end."""
        return next((part for part in self.parts if part), b"")

    @staticmethod
    def _parts(handle: BinaryIO, spans: _Spans) -> Iterator[bytes]:
        data = handle.read(_CHUNK)
        root = _ROOT.search(data)
        plain = root is not None and b"<!ENTITY" not in data[:root.start()]
        start = root.end() if plain else 0
        yield data[:start]
        while plain and data.find(b"<!", start) < 0 and data.find(b"<?", start) < 0:
            end = _record_end_before(data, start, len(data))
            more = handle.read(_CHUNK)
            if end == start and not more:
                break
            # A record longer than a chunk finds its end in the bytes that follow.
            yield b"".join(data[first:last] for first, last in spans(data, start, end))
            data, start = data[end:] + more, 0
        yield data[start:]
        yield from iter(lambda: handle.read(_CHUNK), b"")


def _record_end_before(data: bytes, start: int, at: int) -> int:
    """Return the offset after the last record end tag between two offsets, or the first offset without one."""
    while (at := data.rfind(b"</", start, at)) >= 0:
        match = _RECORD_END.match(data, at)
        if match:
            return match.end()
    return start


def _name_spans(pick: Callable[[list[str]], Collection[str]], entities: dict[str, str]) -> _Spans:
    """Return a test that gives the spans of the records with an author whose name the pick keeps."""
    def spans(data: bytes, start: int, end: int) -> list[tuple[int, int]]:
        raw = _RAW_AUTHOR.findall(data, start, end)
        names = _texts(raw, entities) if len(raw) == data.count(_AUTHOR_TAG, start, end) else None
        if names is None:
            return [(start, end)]
        kept = pick(names)
        found = set()
        for needle in {b">" + one + b"<" for one, name in zip(raw, names) if name in kept} if kept else ():
            at = data.find(needle, start, end)
            while at >= 0:
                found.add((_record_end_before(data, start, at), _RECORD_END.search(data, at).end()))
                at = data.find(needle, at + 1, end)
        return sorted(found)
    return spans


def _texts(raw: list[bytes], entities: dict[str, str]) -> list[str] | None:
    """Return raw author names as lxml reads them, or None where their bytes leave a doubt."""
    try:
        text = _BREAK.encode().join(raw).decode("ascii")
    except UnicodeDecodeError:
        return None
    if "&" in text:
        text = _REFERENCE.sub(lambda reference: _character(reference.group(1), entities), text)
    return None if _DOUBT in text else list(map(str.strip, text.split(_BREAK)))


def _character(reference: str, entities: dict[str, str]) -> str:
    if not reference.startswith("#"):
        return entities.get(reference, _DOUBT)
    try:
        return chr(int(f"0{reference[1:]}", 16) if reference.startswith("#x") else int(reference[1:]))
    except (ValueError, OverflowError):
        return _DOUBT


def _entities(dtd: Path) -> dict[str, str]:
    """Return the text of each entity of the DTD that stands for plain characters, with the five of XML."""
    own = {e.name: e.content for e in etree.DTD(str(dtd)).entities() if e.content and not set("&<") & set(e.content)}
    return {**own, "amp": "&", "lt": "<", "gt": ">", "apos": "'", "quot": '"'}


def _title(element) -> str:
    if element is None:
        return ""
    text = " ".join("".join(element.itertext()).split())
    return text.removesuffix(".")


def _doi(links: list[str]) -> str:
    for link in links:
        match = _DOI.search(link.strip())
        if match:
            return match.group(1).lower()
    for link in links:
        match = _ARXIV.search(link)
        if match:
            return f"10.48550/arxiv.{match.group(1).lower()}"
    return ""


def _resolve(person: Person, scan: _Scan) -> Identity:
    pid = parse_pid(person.dblp)
    if pid:
        for _ in range(MAX_SCANS + 2):
            if pid not in scan.redirects:
                break
            pid = scan.redirects[pid]
        record = scan.records.get(pid)
        if record is None:
            return Identity(pid=pid, method="pid not found")
        return Identity(names=record.names, pid=pid, records=1, method="pid")
    # Records that add middle names join the exact matches, since dblp may keep a person under both forms.
    exact = scan.by_name.get(fold(person.name), [])
    # The other plain spelling of an umlaut, such as Jorg for Joerg, counts only where no record holds the name.
    for spell in (loose_keys, _umlaut_keys):
        keys = spell(person.name)
        loose = [pid for key in keys for pid in scan.by_loose.get(key, [])
                 if _fits(person.name, keys, scan.records[pid], spell)]
        candidates = [scan.records[pid] for pid in dict.fromkeys(exact + loose)]
        if candidates:
            break
    if not candidates:
        return Identity()
    people = [r for r in candidates if not r.disambiguation]
    if len(people) == 1 and len(candidates) == 1:
        method = "name" if people[0].pid in exact else "first and last name"
        return Identity(names=people[0].names, pid=people[0].pid, records=1, method=method)
    wanted = fold(person.affiliation)
    if len(wanted.replace(" ", "")) > SHORT_AFFILIATION:
        fitting = [
            r for r in people
            if any(fuzz.token_set_ratio(wanted, fold(note)) >= AFFILIATION_MIN for note in r.affiliations)
        ]
        if len(fitting) == 1:
            return Identity(names=fitting[0].names, pid=fitting[0].pid, records=1, method="name and affiliation")
    names = tuple(dict.fromkeys(name for r in sorted(candidates, key=lambda r: r.pid) for name in r.names))
    return Identity(names=names, records=len(candidates), ambiguous=True, method="ambiguous name")


def _fits(name: str, keys: tuple[str, ...], record: _Record, spell: Callable[[str], tuple[str, ...]]) -> bool:
    """Return True if a name of the record shares the first and last word in a spelling and fits the middle names."""
    middle = _name_words(base_name(name))[1]
    for other in record.names:
        theirs = _name_words(base_name(other))[1]
        agree = not middle or not theirs or any(one[0] == word[0] for one in middle for word in theirs)
        if agree and not set(keys).isdisjoint(spell(other)):
            return True
    return False

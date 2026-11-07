"""Conflicts of interest between the authors of each paper and the program committee.

The check reuses the methods of the conflict tools of large conferences, applied to EasyChair exports.

- HotCRP (github.com/kohler/hotcrp, Click license), the system of the ICSE 2027 research track, lists
  potential missing conflicts on its page src/pages/p_conflictassign.php by fuzzy matching of
  authors against the names and affiliations of PC members, and lists in a second view the declared
  conflicts that the matching does not support. This module does both. Two affiliations match the
  way HotCRP's AuthorMatcher matches them: one affiliation shares a strong word with the other, or,
  when it has only weak words, all its words appear in the other. A word also appears through one
  of its alternates, such as carnegie mellon for cmu, and counts only where the two affiliations
  agree on its sync words, such as state for arizona, which keeps Arizona State University apart
  from the University of Arizona. The stop words, weak words, alternates, and sync words come from
  HotCRP's etc/affiliationmatchers.json, which the check reads from external/hotcrp/. PeerCheck adds
  placeholders such as N/A to the stop words, and country names, generic words of other languages
  and of fields, such as politecnica and data, and words of at most two letters to the weak words.
  Strong words of five letters or more, without digits, also match a strong word with a rapidfuzz
  ratio of at least affiliation_min, which absorbs typing errors such as Stutgart.
- CLOSET with its EasyChair scripts (github.com/pchrszon/ec-closet-support, MIT) and the scripts of
  ISCA 2018 and ISCA 2021 (github.com/mdrumond/pc-chair-kit, github.com/hibagus/ISCA-2021-Script)
  flag co-authorship in dblp within a number of years. ec-closet-support counts a joint paper when
  the current year minus its year is at most the window, the year arithmetic used here.
- OpenReview (openreview-py, MIT, openreview/tools.py) flags shared email domains and drops webmail
  domains. Its list of common domains opens the webmail list below. A domain counts from its
  registered name on, one label below its public suffix in the Public Suffix List (publicsuffix.org,
  MPL-2.0), which the check reads from external/publicsuffix/, such as ubc.ca for cs.ubc.ca,
  ox.ac.uk for cs.ox.ac.uk, and etri.re.kr for mail.etri.re.kr.

find_conflicts returns one Conflict per paper and PC member with every reason found, and the rows
function turns the conflicts into rows for a sheet with the columns of COLUMNS. A person listed
twice counts once. A PC member who is an author of the paper, by email, dblp person ID, or name, is
reported as such. The dblp person ID is the one given or the one the dblp index resolves, and two
different IDs make two people even under one name. With an EasyChair conflict export, a declared
conflict that no data supports, with no co-authorship in any year, appears with the kind "declared
without support". reviewer_ties lists co-authorship among the assigned reviewers of each paper.

Options (profile key "conflicts"):

- coauthor_years (3): a joint dblp paper counts when its year is at least reference_year minus this
  number. The ACM SIGSOFT Policy on Program Committees counts "a co-author of a paper under
  preparation, submitted, or which was published (or posted online in a digital library or public
  repository such as arXiv) within the past three years" as a conflict
  (https://www2.sigsoft.org/policies/pcpolicy, revised 2026-04).
- reference_year (the current year): the year of the submissions.
- affiliation_min (90): the rapidfuzz ratio at or above which two affiliation words of five letters
  or more count as the same word. ISCA-2021-Script uses 90 as the cutoff of its fuzzy name matches.
- webmail: further email domains to treat as webmail, as a list or as one domain.

The EasyChair readers take the files that ec-closet-support documents: reviewer.csv with the PC
member ID, name, email, and role, and assignment.csv with the PC member ID and the submission ID,
both without a header and separated by commas, semicolons, or tabs. read_pairs reads the conflict
export with the layout of assignment.csv, an assumption that a real export should confirm, and
refuses a file without any pair. The name of a PC member splits at its last space, as
ISCA-2021-Script splits names.
"""

from __future__ import annotations

import csv
import datetime
import functools
import json
from dataclasses import dataclass
from pathlib import Path

from rapidfuzz import fuzz

from peercheck import tools
from peercheck.dblp import DblpIndex, Publication, fold, parse_pid
from peercheck.inputs import InputError
from peercheck.models import Person

DEFAULTS = {"coauthor_years": 3, "reference_year": None, "affiliation_min": 90, "webmail": ()}
COLUMNS = ("Paper", "PC member", "PC member email", "With", "Kinds", "Reasons", "Declared", "Assigned")
LISTED_PAPERS = 3
FUZZY_WORD_MIN = 5

# The affiliation matching below follows AuthorMatcher::test_affiliation in src/authormatcher.php of HotCRP.
# Copyright (c) 2006-2022 Eddie Kohler. Copyright (c) 2006-2008 Regents of the University of California.
# Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
# documentation files (the "Software"), to deal in the Software without restriction, including without limitation
# the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and
# to permit persons to whom the Software is furnished to do so, subject to the following conditions: The above
# copyright notice and this permission notice shall be included in all copies or substantial portions of the
# Software. The names and trademarks of copyright holders may not be used in advertising or publicity pertaining to
# the software without specific prior permission. Title to copyright in this software and any associated
# documentation will at all times remain with the copyright holders. THE SOFTWARE IS PROVIDED "AS IS", WITHOUT
# WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS
# FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR
# ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF
# OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

# Words that people give for no affiliation, such as N/A, which PeerCheck adds to the stop words.
PLACEHOLDER_WORDS = frozenset(["a", "affiliation", "employed", "n", "na", "no", "researcher", "retired", "self"])
# Country names that PeerCheck adds to the weak words, since a shared country never makes a conflict.
COUNTRY_WORDS = frozenset([
    "albania", "algeria", "argentina", "armenia", "austria", "azerbaijan", "bangladesh", "belarus", "belgium",
    "bolivia", "bosnia", "brazil", "bulgaria", "cameroon", "chile", "colombia", "croatia", "cyprus", "czech",
    "czechia", "ecuador", "egypt", "emirates", "estonia", "ethiopia", "finland", "ghana", "greece", "herzegovina",
    "hungary", "iceland", "indonesia", "iran", "iraq", "ireland", "japan", "jordan", "kazakhstan", "kenya", "kingdom",
    "korea", "kuwait", "latvia", "lebanon", "lithuania", "luxembourg", "macedonia", "malaysia", "malta", "mexico",
    "moldova", "mongolia", "montenegro", "morocco", "nepal", "netherlands", "nigeria", "norway", "oman", "pakistan",
    "palestine", "peru", "philippines", "poland", "portugal", "qatar", "republic", "romania", "russia", "rwanda",
    "saudi", "arabia", "serbia", "slovakia", "slovenia", "spain", "sri", "lanka", "states", "sweden", "switzerland",
    "syria", "taiwan", "tanzania", "thailand", "tunisia", "turkey", "turkiye", "uganda", "ukraine", "uruguay",
    "uzbekistan", "venezuela", "vietnam", "zealand", "zimbabwe"
])
# Generic words of organization names in other languages and names of fields, which PeerCheck adds to the weak words.
GENERIC_WORDS = frozenset([
    "artificial", "autonoma", "catholique", "catolica", "cattolica", "centro", "ciencia", "ciencias", "computacao",
    "computacion", "computation", "computational", "cyber", "das", "data", "degli", "dei", "del", "della", "delle",
    "dello", "departamento", "departement", "der", "des", "die", "digital", "dipartimento", "dos", "electrical",
    "engenharia", "escola", "escuela", "estadual", "facolta", "facultad", "faculdade", "faculte", "fakultat", "federale",
    "forschung", "fur", "informatica", "informatik", "informatique", "ingegneria", "ingenieria", "institutet",
    "institutt", "instytut", "intelligence", "investigacion", "istituto", "katholieke", "laboratoire", "laboratorio",
    "las", "learning", "lehrstuhl", "les", "machine", "mechanical", "nacional", "nationale", "nazionale", "pesquisa",
    "physics", "politechnika", "politecnica", "politehnica", "pontifical", "pontificia", "recherche", "ricerca",
    "robotics", "scienze", "scuola", "statistics", "studi", "studies", "superieure", "superior", "superiore", "tecnica",
    "tecnico", "tecnologia", "tecnologica", "tecnologico", "und", "uni", "universitaet", "universitaire",
    "universitaria", "universitario", "universitas", "universitatea", "universitet", "universiteti", "universiti",
    "univerza", "univerzita", "uniwersytet"
])
# The common domains of OpenReview's conflict code, then further webmail providers.
WEBMAIL = frozenset([
    "gmail.com", "qq.com", "126.com", "163.com", "outlook.com", "hotmail.com", "yahoo.com", "foxmail.com", "aol.com",
    "msn.com", "ymail.com", "googlemail.com", "live.com", "independent-researcher.org",
    "icloud.com", "me.com", "mac.com", "proton.me", "protonmail.com", "pm.me", "gmx.de", "gmx.net", "gmx.com",
    "web.de", "t-online.de", "posteo.de", "mailbox.org", "yandex.ru", "yandex.com", "mail.ru", "naver.com",
    "hanmail.net", "daum.net", "sina.com", "sina.cn", "sohu.com", "yeah.net", "aliyun.com", "139.com", "zoho.com",
    "fastmail.com", "tutanota.com", "hey.com", "libero.it", "orange.fr", "free.fr", "laposte.net", "rediffmail.com",
    "mail.com", "email.com", "tuta.io", "tuta.com", "tutanota.de", "fastmail.fm", "zohomail.com", "hushmail.com",
    "mailfence.com", "duck.com", "189.cn", "188.com", "21cn.com", "tom.com", "kakao.com", "nate.com", "rambler.ru",
    "bk.ru", "list.ru", "inbox.ru", "ya.ru", "ukr.net", "seznam.cz", "email.cz", "centrum.cz", "wp.pl", "o2.pl",
    "onet.pl", "op.pl", "interia.pl", "abv.bg", "freemail.hu", "virgilio.it", "tiscali.it", "alice.it", "sfr.fr",
    "wanadoo.fr", "freenet.de", "arcor.de", "sapo.pt", "uol.com.br", "bol.com.br", "terra.com.br", "ig.com.br",
    "btinternet.com", "comcast.net", "verizon.net", "att.net", "sbcglobal.net", "bigpond.com", "shaw.ca", "walla.co.il",
])
# Providers whose country domains, such as yahoo.co.uk or hotmail.fr, are webmail as well.
WEBMAIL_PROVIDERS = frozenset(["gmail", "googlemail", "hotmail", "outlook", "live", "yahoo", "ymail", "aol", "icloud",
                               "protonmail", "gmx", "yandex"])


@dataclass(frozen=True)
class Conflict:
    """One possible conflict between a PC member and a paper, with every reason found."""

    paper_id: int
    member: Person
    others: tuple[Person, ...]
    kinds: tuple[str, ...]
    reasons: tuple[str, ...]
    declared: bool | None = None
    assigned: bool | None = None


def find_conflicts(
    authors: dict[int, list[Person]],
    committee: list[Person],
    index: DblpIndex | None = None,
    assignments: dict[int, list[Person]] | None = None,
    declared: dict[int, list[Person]] | None = None,
    options: dict | None = None,
) -> list[Conflict]:
    """Return the possible conflicts of each paper with each PC member, and declared conflicts without support."""
    settings = {**DEFAULTS, **(options or {})}
    since = _since(settings)
    extra = settings["webmail"] or ()
    webmail = WEBMAIL | {domain.strip().lower() for domain in ([extra] if isinstance(extra, str) else extra)}
    minimum = int(settings["affiliation_min"])
    works = _Works(index)
    found = []
    committee = list(dict.fromkeys(committee))
    for paper_id in sorted(authors):
        people = list(dict.fromkeys(authors[paper_id]))
        for member in committee:
            kinds: list[str] = []
            reasons: list[str] = []
            others: list[Person] = []
            for author in people:
                pair = _pair(author, member, works, since, webmail, minimum)
                if pair:
                    others.append(author)
                    kinds.extend(kind for kind, _ in pair if kind not in kinds)
                    reasons.extend(reason for _, reason in pair)
            is_declared = None if declared is None else _among(member, declared.get(paper_id, []), works)
            is_assigned = None if assignments is None else _among(member, assignments.get(paper_id, []), works)
            if not kinds and is_declared:
                reason = _unsupported(people, member, works)
                if not reason:
                    continue
                kinds, reasons = ["declared without support"], [reason]
            if kinds:
                found.append(Conflict(paper_id, member, tuple(others), tuple(kinds), tuple(reasons), is_declared,
                                      is_assigned))
    return found


def reviewer_ties(assignments: dict[int, list[Person]], index: DblpIndex, options: dict | None = None) -> list[Conflict]:
    """Return the pairs of assigned reviewers of one paper who wrote a dblp paper together within the window."""
    since = _since({**DEFAULTS, **(options or {})})
    works = _Works(index)
    found = []
    for paper_id in sorted(assignments):
        reviewers: list[Person] = []
        for person in assignments[paper_id]:
            if not any(_same(person, other, works) for other in reviewers):
                reviewers.append(person)
        for i, first in enumerate(reviewers):
            for second in reviewers[i + 1:]:
                joint = works.joint(first, second, since)
                if joint:
                    found.append(Conflict(
                        paper_id, first, (second,), ("reviewer co-authorship",),
                        (_coauthor_reason(first, second, joint, index, since),), None, True,
                    ))
    return found


def rows(conflicts: list[Conflict]) -> list[dict[str, str]]:
    """Return the conflicts as rows for a sheet, keyed by the names of COLUMNS."""
    return [
        dict(zip(COLUMNS, (
            str(c.paper_id), c.member.name, c.member.email, "; ".join(p.name for p in c.others), "; ".join(c.kinds),
            "\n".join(c.reasons), _flag(c.declared), _flag(c.assigned),
        )))
        for c in conflicts
    ]


def affiliation_match(first: str, second: str, minimum: int = DEFAULTS["affiliation_min"]) -> str:
    """Return the affiliation words that make two affiliations match, or an empty string."""
    for one in first.split(";"):
        for other in second.split(";"):
            for a, b in ((one, other), (other, one)):
                words = _shared_words(a, b, minimum)
                if words:
                    return words
    return ""


@functools.cache
def org_domain(email: str) -> str:
    """Return the registered domain of an email address, such as ox.ac.uk for a@cs.ox.ac.uk."""
    labels = [label for label in email.rpartition("@")[2].strip().lower().split(".") if label]
    rules, exceptions = _public_suffixes()
    suffixes = [".".join(labels[start:]) for start in range(len(labels))]
    for suffix in suffixes:
        if suffix in exceptions:
            return suffix
    for start, suffix in enumerate(suffixes):
        if suffix in rules or ".".join(["*", *labels[start + 1:]]) in rules:
            return suffixes[start - 1] if start else ""
    return ""


def read_members(path: Path) -> dict[int, Person]:
    """Read the PC members of an EasyChair reviewer.csv, keyed by PC member ID."""
    members = {}
    for row in _csv_rows(path):
        if len(row) >= 2 and row[0].strip().isdigit():
            first, _, last = row[1].strip().rpartition(" ")
            members[int(row[0])] = Person(first=first, last=last, email=row[2].strip() if len(row) > 2 else "")
    return members


def read_pairs(path: Path, members: dict[int, Person]) -> dict[int, list[Person]]:
    """Read the PC member and submission pairs of an EasyChair assignment.csv or conflict export, keyed by paper."""
    pairs: dict[int, list[Person]] = {}
    for row in _csv_rows(path):
        if len(row) < 2 or not (row[0].strip().isdigit() and row[1].strip().isdigit()):
            continue
        member = members.get(int(row[0]))
        if member is None:
            raise InputError(f"{path.name}: PC member {row[0].strip()} is not in the reviewer list")
        pairs.setdefault(int(row[1]), []).append(member)
    if not pairs:
        raise InputError(f"{path.name}: no row holds a PC member ID and a submission ID")
    return pairs


class _Works:
    """The dblp publications of each person from a year on, looked up once per person and year."""

    def __init__(self, index: DblpIndex | None) -> None:
        self.index = index
        self.cache: dict[tuple[Person, int | None], dict[str, Publication]] = {}
        self.pids: dict[Person, str] = {}

    def joint(self, first: Person, second: Person, since: int | None) -> list[Publication]:
        """Return the publications of two people together from a year on, empty without an index."""
        if self.index is None:
            return []
        mine = self._of(first, since)
        return [publication for key, publication in self._of(second, since).items() if key in mine]

    def known(self, person: Person) -> bool:
        """Return True if the index holds dblp names for a person."""
        identity = self.index.identity(person) if self.index is not None else None
        return identity is not None and bool(identity.names)

    def pid(self, person: Person) -> str:
        """Return the dblp person ID that the index resolves for a person, or else the one given, or nothing."""
        if person not in self.pids:
            identity = self.index.identity(person) if self.index is not None else None
            resolved = identity.pid if identity is not None and not identity.ambiguous else ""
            self.pids[person] = resolved or parse_pid(person.dblp)
        return self.pids[person]

    def _of(self, person: Person, since: int | None) -> dict[str, Publication]:
        if (person, since) not in self.cache:
            self.cache[person, since] = {p.key: p for p in self.index.publications_of(person, since)}
        return self.cache[person, since]


def _pair(author: Person, member: Person, works: _Works, since: int, webmail: frozenset[str],
          minimum: int) -> list[tuple[str, str]]:
    how = _same(author, member, works)
    if how:
        return [("author", f"{member.name} is an author of the paper (same {how})")]
    found = []
    joint = works.joint(author, member, since)
    if joint:
        found.append(("co-author", _coauthor_reason(member, author, joint, works.index, since)))
    domain = org_domain(author.email) if author.email and member.email else ""
    if domain and domain == org_domain(member.email) and not _webmail(domain, webmail):
        found.append(("email domain", f"{member.name} and {author.name} share the email domain {domain}"))
    words = affiliation_match(author.affiliation, member.affiliation, minimum)
    if words:
        reason = f"{member.name} ({member.affiliation}) and {author.name} ({author.affiliation}) share the words {words}"
        found.append(("affiliation", reason))
    return found


def _coauthor_reason(member: Person, other: Person, joint: list[Publication], index: DblpIndex, since: int) -> str:
    joint = sorted(joint, key=lambda p: (-(p.year or 0), p.key))
    listed = "; ".join(f"{p.title} ({p.year}, dblp {p.key})" for p in joint[:LISTED_PAPERS])
    more = f"; and {len(joint) - LISTED_PAPERS} more" if len(joint) > LISTED_PAPERS else ""
    papers = "1 dblp paper" if len(joint) == 1 else f"{len(joint)} dblp papers"
    reason = f"{member.name} and {other.name} wrote {papers} together since {since}: {listed}{more}"
    for person in (member, other):
        identity = index.identity(person)
        if identity is not None and identity.ambiguous:
            reason += f". The name {person.name} matches {identity.records} dblp person records; confirm the person"
    return reason


def _unsupported(authors: list[Person], member: Person, works: _Works) -> str:
    if any(works.joint(author, member, None) for author in authors):
        return ""
    shared = "an email domain or an affiliation" if works.index is None else \
        "a dblp paper, an email domain, or an affiliation"
    reason = f"declared in the conflict export, while no author shares {shared} with {member.name}"
    if works.index is not None:
        unknown = sum(1 for author in authors if not works.known(author))
        if unknown:
            reason += f"; dblp has no record for {unknown} of {len(authors)} authors"
    return reason


def _shared_words(text: str, subject: str, minimum: int) -> str:
    words, found = _words(text), _words(subject)
    seen = [_seen(word, words, found, minimum) for word in words]
    strong = sorted(label for label, weak in seen if label and not weak)
    if strong:
        return " ".join(strong)
    return " ".join(sorted(label for label, _ in seen)) if seen and all(label for label, _ in seen) else ""


def _seen(word: str, words: frozenset[str], found: frozenset[str], minimum: int) -> tuple[str, bool]:
    rule = _rules().get(word, {})
    weak = _weak(word)
    label = word if word in found or (not weak and _similar(word, found, minimum)) else ""
    if not label:
        for alternate in rule.get("alternate", ()):
            if isinstance(alternate, dict):
                if not _applies(alternate, words):
                    continue
                alternate = alternate["word"]
            if found.issuperset(alternate.split()):
                label = f"{word} ({alternate})"
                # A weak word seen as one strong word, such as massachusetts as mit, counts as strong.
                weak = weak and (" " in alternate or _weak(alternate))
                break
    return (label, weak) if label and _synced(rule.get("sync", ()), words, found) else ("", weak)


def _similar(word: str, found: frozenset[str], minimum: int) -> bool:
    # Only strong words of letters match by spelling, since Place12 and Place123 name different places and a
    # misspelled Universty would otherwise match every University.
    return len(word) >= FUZZY_WORD_MIN and word.isalpha() and any(
        len(other) >= FUZZY_WORD_MIN and other.isalpha() and not _weak(other) and fuzz.ratio(word, other) >= minimum
        for other in found
    )


def _applies(alternate: dict, words: frozenset[str]) -> bool:
    # HotCRP skips an alternate unless all its if words are present, and when all its if_not words are.
    return words.issuperset(alternate.get("if", "").split()) and not (
        alternate.get("if_not") and words.issuperset(alternate["if_not"].split()))


def _synced(sync: str | list[str], words: frozenset[str], found: frozenset[str]) -> bool:
    # Each group of sync words appears in both affiliations or in neither, such as state for arizona.
    groups = [sync] if isinstance(sync, str) else sync
    return all(bool(words.intersection(group.split())) == bool(found.intersection(group.split())) for group in groups)


@functools.cache
def _words(text: str) -> frozenset[str]:
    return frozenset(
        word for word in fold(text).split() if word not in PLACEHOLDER_WORDS and not _rules().get(word, {}).get("stop")
    )


@functools.cache
def _weak(word: str) -> bool:
    return len(word) <= 2 or word in COUNTRY_WORDS or word in GENERIC_WORDS or bool(_rules().get(word, {}).get("weak"))


@functools.cache
def _rules() -> dict[str, dict]:
    return json.loads(tools.external("hotcrp/affiliationmatchers.json").read_text(encoding="utf-8"))


@functools.cache
def _public_suffixes() -> tuple[frozenset[str], frozenset[str]]:
    lines = tools.external("publicsuffix/public_suffix_list.dat").read_text(encoding="utf-8").splitlines()
    rules = {line.split()[0] for line in lines if line.strip() and not line.startswith("//")}
    # The rule * applies where no other rule does, which makes an unknown top-level domain a public suffix.
    return frozenset(r for r in rules if r[0] != "!") | {"*"}, frozenset(r[1:] for r in rules if r[0] == "!")


def _same(first: Person, second: Person, works: _Works) -> str:
    if first.email and second.email and first.email.strip().lower() == second.email.strip().lower():
        return "email"
    one, other = works.pid(first), works.pid(second)
    if one and other:
        # Two dblp persons are two people, even under one name.
        return "dblp person ID" if one == other else ""
    return "name" if _name(first.name) and _name(first.name) == _name(second.name) else ""


@functools.cache
def _name(name: str) -> str:
    return fold(name)


def _among(person: Person, people: list[Person], works: _Works) -> bool:
    return any(_same(person, other, works) for other in people)


def _webmail(domain: str, webmail: frozenset[str]) -> bool:
    return domain in webmail or domain.split(".")[0] in WEBMAIL_PROVIDERS


def _since(settings: dict) -> int:
    year = settings["reference_year"] or datetime.date.today().year
    return int(year) - int(settings["coauthor_years"])


def _flag(value: bool | None) -> str:
    return "" if value is None else ("yes" if value else "no")


def _csv_rows(path: Path) -> list[list[str]]:
    if not path.is_file():
        raise InputError(f"file not found: {path}")
    with path.open(encoding="utf-8-sig", newline="") as handle:
        sample = handle.read(4096)
        handle.seek(0)
        try:
            delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t").delimiter
        except csv.Error:
            delimiter = ","
        return list(csv.reader(handle, delimiter=delimiter))

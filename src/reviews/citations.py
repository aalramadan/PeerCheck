"""Citation requests in reviews, including requests for works by the reviewers of the same paper.

The check reads Review.author_text and extracts three kinds of items.

- DOIs, with the pattern that Crossref recommends for modern DOIs, 10.\\d{4,9}/[-._;()/:A-Z0-9]+
  (https://www.crossref.org/blog/dois-and-matching-regular-expressions/).
- arXiv identifiers of the two arXiv schemes, YYMM.NNNNN and archive/YYMMNNN, after the word arXiv
  or in an arxiv.org link.
- Reference-like strings, namely a numbered or bulleted line with a year and a mark of a reference
  (et al., initials, a venue, or pages), an author-year citation such as "Smith et al. (2020)", and
  a quoted title in title case.

A review with items gets citations.requests (INFO) with their count, the items, and any request
phrase such as "should cite". A review that cites more works than the paper has pages gets
citations.many-requests (WARNING). Wren, Valencia, and Kelso (Bioinformatics 35(18):3217-3218, 2019,
doi:10.1093/bioinformatics/btz071) propose "more than one reference per printed journal page of the
paper" as the rule of thumb for a substantial request.

With a dblp index, the items are matched against the publications of the reviewers of the paper:
the author of the review (Review.reviewer), the authors of the other reviews of the same paper, and
the reviewers that the assignments name. Barnett (eLife 2025, doi:10.7554/eLife.108748) matched the
DOIs cited in reviews to the publications of the reviewers in the same way. An item matches a
publication by DOI (arXiv items through the arXiv DOI 10.48550/arXiv.<id>), by a publication title
that the item contains, or, for an author-year citation, by the surname of the first author and the
year. Each reviewer with matches gives citations.self-citation-request (WARNING) with the matched
dblp records and, for the author of the review, the number of that reviewer's reviews with such
requests.

Options (profile key "citations"):

- dblp_index: a DblpIndex, or the path of a file that DblpIndex.save wrote. Without an index the
  check skips the self-citation part.
- assignments: a mapping from paper ID to the reviewers (Person) assigned to the paper.
- pages (10): the page count of the papers, one number for all or a mapping from paper ID to pages.
  The default is the main page limit of the ICSE 2027 research track.
- title_min (90): the rapidfuzz partial ratio at or above which a publication title counts as
  present in an item. Titles shorter than 20 characters never match this way.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, replace
from pathlib import Path

from rapidfuzz import fuzz

from peercheck.dblp import DblpIndex, Publication, base_name, fold, load_index
from peercheck.findings import Finding, Severity
from peercheck.models import Person, Review

DEFAULTS = {"dblp_index": None, "assignments": None, "pages": 10, "title_min": 90}
TITLE_MIN_CHARS = 20
_DOI = re.compile(r"\b(10\.\d{4,9}/[-._;()/:a-z0-9]+)", re.IGNORECASE)
_ARXIV = re.compile(
    r"arxiv(?:\.org/(?:abs|pdf)/|\s*:\s*|\s+)((?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[a-z]{2})?/\d{7}))(?:v\d+)?",
    re.IGNORECASE,
)
_LETTERS = r"[^\W\d_](?:[^\W\d_]|['’-])*"
_YEAR = r"((?:19|20)\d{2})[a-z]?"
_ET_AL = re.compile(rf"\b({_LETTERS})\s+et\s+al\.?,?\s*[(\[]?\s*{_YEAR}\s*[)\]]?")
_TWO = re.compile(rf"\b({_LETTERS})\s+(?:and|&)\s+{_LETTERS},?\s*[(\[]\s*{_YEAR}\s*[)\]]")
_ONE = re.compile(rf"\b({_LETTERS})\s+[(\[]\s*{_YEAR}\s*[)\]]")
_QUOTED = re.compile(r"[\"“]([^\"”\n]{15,250})[\"”]")
_LIST_ITEM = re.compile(r"^\s*(?:\[\d{1,3}\]|\d{1,3}[.)]|[-*•])\s+")
_HAS_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
# A line that opens with initials and a surname, or with a surname, a comma, and an initial.
_REFERENCE_START = re.compile(r"^(?:[A-Z]\.\s?(?:[A-Z]\.\s?)?[^\W\d_]{2,}|[^\W\d_]{2,},\s+[A-Z]\.)")
_REFERENCE_MARK = re.compile(
    r"et al\.|\bProc(?:eedings|\.)|\bJournal\b|\bTrans(?:actions|\.)|\bpp\.\s*\d|\bvol\.\s*\d"
    r"|\b[A-Z]\.\s?(?:[A-Z]\.\s?)?[A-Z][a-z]+|\b[A-Z][a-z]+,\s+[A-Z]\."
    r"|\b(?:ICSE|FSE|ESEC|ASE|ISSTA|ICSME|SANER|MSR|ICST|ICPC|OOPSLA|PLDI|POPL|TSE|TOSEM|EMSE|NeurIPS|ICML|ICLR|ACL"
    r"|EMNLP|CHI|CSCW)\b"
)
_REQUEST = re.compile(
    r"\b(?:please\s+(?:also\s+)?cite|should\s+(?:also\s+)?(?:cite|discuss|refer\s+to|compare\s+(?:with|to|against))"
    r"|consider\s+(?:citing|discussing|referring\s+to)|(?:is|are)\s+not\s+(?:cited|referenced)"
    r"|(?:missing|lacks?|overlooks?|omits?)\s+(?:\w+\s+){0,3}?(?:references?|citations?|related\s+work|prior\s+work)"
    r"|(?:must|should|needs?\s+to)\s+(?:also\s+)?be\s+(?:cited|discussed|referenced)"
    r"|(?:references?|citations?|related\s+work|prior\s+work)\s+(?:is|are)\s+(?:missing|incomplete))\b",
    re.IGNORECASE,
)
# Capitalized words that precede a year in text without being a surname.
_NOT_SURNAMES = {
    "in", "on", "at", "by", "since", "from", "until", "after", "before", "during", "the", "this", "that", "these",
    "those", "section", "table", "figure", "fig", "version", "release", "year", "spring", "summer", "fall", "autumn",
    "winter", "january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
    "november", "december", "java", "python", "and", "or", "see", "also", "e", "g", "i",
}


@dataclass(frozen=True)
class Item:
    """One work that a review names, with what the matching needs."""

    kind: str
    text: str
    doi: str = ""
    surname: str = ""
    year: int | None = None


def check_reviews(reviews: list[Review], options: dict) -> dict[str, list[Finding]]:
    """Return the citation findings of each review, keyed by review ID."""
    settings = {**DEFAULTS, **(options or {})}
    index = settings["dblp_index"]
    if isinstance(index, (str, Path)):
        index = load_index(Path(index))
    findings: dict[str, list[Finding]] = {review.review_id: [] for review in reviews}
    requests = []
    for review in reviews:
        items = extract(review.author_text)
        if items:
            findings[review.review_id].extend(_requests(review, items, _pages(settings["pages"], review.paper_id)))
            requests.append((review, items))
    if index is None:
        return findings
    panels = _panels(reviews, settings["assignments"] or {})
    works: dict[str, list[Publication]] = {}
    hits = []
    for review, items in requests:
        for reviewer in panels.get(review.paper_id, []):
            if _key(reviewer) not in works:
                works[_key(reviewer)] = index.publications_of(reviewer)
            matches = _matches(items, works[_key(reviewer)], int(settings["title_min"]))
            if matches:
                hits.append((review, reviewer, matches))
    written = Counter(_key(review.reviewer) for review in reviews if review.reviewer is not None)
    asking = Counter(_key(review.reviewer) for review, reviewer, _ in hits if _is_author(review, reviewer))
    for review, reviewer, matches in hits:
        finding = _self_request(review, reviewer, matches, index)
        if _is_author(review, reviewer):
            key = _key(review.reviewer)
            finding = replace(finding, evidence=f"{finding.evidence}; this reviewer asks for own works in "
                                                f"{asking[key]} of {written[key]} reviews")
        findings[review.review_id].append(finding)
    return findings


def extract(text: str) -> list[Item]:
    """Return the DOIs, arXiv identifiers, and reference-like strings of a review text, without repeats."""
    items: list[Item] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        taken: list[tuple[int, int]] = []
        for match in _DOI.finditer(line):
            items.append(Item("doi", _short(line), doi=_trim_doi(match.group(1))))
            taken.append(match.span())
        for match in _ARXIV.finditer(line):
            items.append(Item("arxiv", _short(line), doi=f"10.48550/arxiv.{match.group(1).lower()}"))
            taken.append(match.span())
        listed = _LIST_ITEM.match(line) and _REFERENCE_MARK.search(line)
        if _HAS_YEAR.search(line) and (listed or _REFERENCE_START.match(line)):
            # A reference entry names one work, already counted when it carries a DOI or an arXiv identifier.
            if not taken:
                items.append(Item("reference", _short(_LIST_ITEM.sub("", line))))
            continue
        for pattern in (_ET_AL, _TWO, _ONE):
            for match in pattern.finditer(line):
                surname = match.group(1)
                if _overlaps(match.span(), taken) or not _is_surname(surname):
                    continue
                items.append(Item("citation", match.group(0).strip(" ,"), surname=surname, year=int(match.group(2))))
                taken.append(match.span())
        for match in _QUOTED.finditer(line):
            if _is_title(match.group(1)):
                items.append(Item("title", match.group(1).strip()))
    unique: dict[tuple[str, str], Item] = {}
    for item in items:
        unique.setdefault((item.doi or item.kind, item.doi or fold(item.text)), item)
    return list(unique.values())


def _requests(review: Review, items: list[Item], pages: int) -> list[Finding]:
    phrases = sorted({m.group(0).lower() for m in _REQUEST.finditer(review.author_text)})
    asks = f", with the request phrases {'; '.join(phrases)}" if phrases else ""
    found = [Finding(
        check="citations.requests",
        severity=Severity.INFO,
        message=f"The review cites {_works(len(items))}{asks}",
        evidence="; ".join(f"{item.kind}: {item.doi or item.text}" for item in items),
    )]
    if len(items) > pages:
        found.append(Finding(
            check="citations.many-requests",
            severity=Severity.WARNING,
            message=f"The review cites {_works(len(items))}, more than one per page of a {pages}-page paper",
            evidence="Wren, Valencia, and Kelso (Bioinformatics 2019) call more than one requested reference per "
                     "printed page of the paper substantial",
        ))
    return found


def _matches(items: list[Item], publications: list[Publication], title_min: int) -> list[tuple[Item, Publication, str]]:
    found = []
    for item in items:
        for publication in publications:
            how = _match(item, publication, title_min)
            if how:
                found.append((item, publication, how))
    return found


def _match(item: Item, publication: Publication, title_min: int) -> str:
    if item.doi and item.doi == publication.doi:
        return "DOI"
    if item.surname:
        first = fold(base_name(publication.authors[0])).split() if publication.authors else []
        if first and first[-1] == fold(item.surname) and publication.year == item.year:
            return "first author and year"
        return ""
    title = fold(publication.title)
    if len(title) >= TITLE_MIN_CHARS and fuzz.partial_ratio(title, fold(item.text)) >= title_min:
        return "title"
    return ""


def _self_request(review: Review, reviewer: Person, matches, index: DblpIndex) -> Finding:
    works = {publication.key for _, publication, _ in matches}
    if _is_author(review, reviewer):
        who = f"its own reviewer {reviewer.name}"
    elif review.reviewer is not None:
        who = f"{reviewer.name}, another reviewer of paper {review.paper_id}"
    else:
        who = f"{reviewer.name}, a reviewer of paper {review.paper_id}"
    identity = index.identity(reviewer)
    note = ""
    if identity is not None and identity.ambiguous:
        note = f" The name {reviewer.name} matches {identity.records} dblp person records; confirm the person."
    return Finding(
        check="citations.self-citation-request",
        severity=Severity.WARNING,
        message=f"The review asks for {_works(len(works))} by {who}.{note}",
        evidence="; ".join(
            f"{item.doi or item.text} matches dblp {publication.key} ({publication.year}, {publication.title}) by {how}"
            for item, publication, how in matches
        ),
    )


def _is_author(review: Review, reviewer: Person) -> bool:
    return review.reviewer is not None and _same(review.reviewer, reviewer)


def _panels(reviews: list[Review], assignments: dict[int, list[Person]]) -> dict[int | None, list[Person]]:
    """Return the reviewers of each paper, each person once, the authors of its reviews first."""
    panels: dict[int | None, list[Person]] = {}
    pairs = [(r.paper_id, r.reviewer) for r in reviews if r.reviewer is not None]
    pairs += [(paper_id, person) for paper_id, people in assignments.items() for person in people]
    for paper_id, person in pairs:
        panel = panels.setdefault(paper_id, [])
        if not any(_same(person, other) for other in panel):
            panel.append(person)
    return panels


def _pages(pages, paper_id: int | None) -> int:
    if isinstance(pages, dict):
        return int(pages.get(paper_id, DEFAULTS["pages"]))
    return int(pages)


def _key(person: Person) -> str:
    return person.email.strip().lower() or fold(person.name)


def _same(first: Person, second: Person) -> bool:
    if first.email and second.email:
        return first.email.strip().lower() == second.email.strip().lower()
    return fold(first.name) == fold(second.name)


def _trim_doi(doi: str) -> str:
    doi = doi.rstrip(".,;:")
    while doi.endswith(")") and doi.count(")") > doi.count("("):
        doi = doi[:-1].rstrip(".,;:")
    return doi.lower()


def _is_surname(word: str) -> bool:
    return word[0].isupper() and not word.isupper() and word.lower() not in _NOT_SURNAMES


def _is_title(text: str) -> bool:
    words = [w for w in re.findall(r"[^\W\d_]+", text) if len(w) >= 4]
    return len(text.split()) >= 3 and bool(words) and sum(w[0].isupper() for w in words) >= 0.6 * len(words)


def _overlaps(span: tuple[int, int], taken: list[tuple[int, int]]) -> bool:
    return any(start < span[1] and span[0] < end for start, end in taken)


def _short(text: str, limit: int = 160) -> str:
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def _works(count: int) -> str:
    return "1 work" if count == 1 else f"{count} works"

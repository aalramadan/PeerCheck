"""Looks up cited works in open indexes over HTTPS, by DOI in DataCite, in Crossref, and at doi.org, and by title in
DataCite, OpenAlex, and OpenReview. DataCite holds every arXiv preprint and Zenodo upload, Crossref the articles of most
publishers, OpenAlex also books and older works, and OpenReview the papers of a venue before a database lists them.
"""

from __future__ import annotations

import collections
import html
import http.client
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

DATACITE_URL = "https://api.datacite.org/dois"
CROSSREF_URL = "https://api.crossref.org/works"
DOI_AGENCY_URL = "https://doi.org/doiRA"
OPENALEX_URL = "https://api.openalex.org/works"
OPENREVIEW_URL = "https://api2.openreview.net/notes/search"
ARXIV_DOI = "10.48550/arxiv."
ARXIV_VERSION = re.compile(r"v\d+$")
NOT_WORD = re.compile(r"[^\w\s]+")
MARKUP = re.compile(r"<[^>]+>")
# DataCite, Crossref, and doi.org answer this many DOIs in one request.
BATCH = 50
# The types of a Crossref record that names a whole publication, such as the volume that holds a paper.
CONTAINERS = frozenset({"journal", "journal-volume", "journal-issue", "proceedings", "proceedings-series", "book",
                        "edited-book", "reference-book", "monograph", "book-series", "book-set", "report-series"})
# A phrase such as Attention Is All You Need stands in the titles of many records, with the best matches first.
RECORDS = 10
TIMEOUT = 20
# A request that a service turns away for at most this many seconds goes out once more after that time.
LONGEST_WAIT = 60
# The statuses with which a service asks a client to come back later: too many requests, and not available.
COME_BACK = (429, 503)
# A failed request raises one of these, such as a refused connection, a full daily budget, an answer that ends
# early, or an answer in another form.
LOOKUP_ERRORS = (OSError, ValueError, KeyError, TypeError, AttributeError, http.client.HTTPException)


@dataclass(frozen=True)
class Work:
    """The title and the authors of one record of an index, each author with the family name last. A container is
    a whole publication, such as a proceedings volume or a journal."""

    title: str
    authors: tuple[str, ...]
    container: bool = False


class Pace:
    """Holds a request back until a service that answers a number of requests in a time window takes it."""

    def __init__(self, requests: int, window: float):
        self.window = window
        self.times: collections.deque[float] = collections.deque(maxlen=requests)
        self.turn = threading.Lock()

    def wait(self) -> None:
        """Return at once, or once the oldest of the last requests has left the window."""
        with self.turn:
            if len(self.times) == self.times.maxlen:
                time.sleep(max(0.0, self.times[0] + self.window - time.monotonic()))
            self.times.append(time.monotonic())


class Budget:
    """The seconds that the requests of one run get, counted from the start of the run."""

    def __init__(self, seconds: float):
        self.end = time.monotonic() + seconds

    def is_spent(self) -> bool:
        return time.monotonic() >= self.end


# OpenReview answers 20 requests a minute, and two more seconds allow for the way of a request.
OPENREVIEW_PACE = Pace(20, 62.0)
# Crossref answers one request for several works per second to a client that names no address.
CROSSREF_PACE = Pace(1, 1.0)


def datacite_doi_works(dois: list[str]) -> dict[str, Work]:
    """Return the DataCite record of each of up to 50 DOIs that has one, by the DOI in lower case.

    arXiv registers the DOI 10.48550/arXiv.<ID> for every preprint, with the title and the authors of its newest
    version, while the API of arXiv allows one request in three seconds."""
    # A quote or a backslash would end the quoted DOI in the query.
    dois = [doi for doi in dois if '"' not in doi and "\\" not in doi]
    if not dois:
        return {}
    query = "doi:(" + " OR ".join(f'"{doi.lower()}"' for doi in dois) + ")"
    answer = _answer(DATACITE_URL, {"query": query, "page[size]": BATCH, "fields[dois]": "titles,creators"})
    return {record["id"].lower(): _datacite_work(record["attributes"]) for record in answer["data"]}


def crossref_doi_works(dois: list[str]) -> dict[str, Work]:
    """Return the Crossref record of each of up to 50 DOIs that has one, by the DOI in lower case.

    The address in CROSSREF_MAILTO, when set, goes with the request, since Crossref answers a client that names
    an address faster."""
    # A comma would end the DOI in the filter.
    dois = [doi for doi in dois if "," not in doi]
    if not dois:
        return {}
    query = {"filter": ",".join(f"doi:{doi.lower()}" for doi in dois), "rows": BATCH,
             "select": "DOI,title,subtitle,author,type"}
    if os.environ.get("CROSSREF_MAILTO"):
        query["mailto"] = os.environ["CROSSREF_MAILTO"]
    CROSSREF_PACE.wait()
    records = _answer(CROSSREF_URL, query)["message"]["items"]
    return {record["DOI"].lower(): _crossref_work(record) for record in records}


def doi_agencies(dois: list[str]) -> dict[str, str]:
    """Return the registration agency of each of up to 50 DOIs that exists, such as Crossref, DataCite, ISTIC, or
    JaLC, by the DOI in lower case."""
    # A comma would end the DOI in the address.
    dois = [doi for doi in dois if "," not in doi]
    if not dois:
        return {}
    asked = ",".join(urllib.parse.quote(doi.lower(), safe="/") for doi in dois)
    return {row["DOI"].lower(): row["RA"] for row in _answer(f"{DOI_AGENCY_URL}/{asked}", {}) if "RA" in row}


def datacite_works(title: str) -> list[Work]:
    """Return the DataCite records whose title holds the words of a title in their order, the best matches first."""
    # Without the sort, DataCite returns its newest records first.
    query = {"query": f'titles.title:"{_words(title)}"', "sort": "relevance", "page[size]": RECORDS,
             "fields[dois]": "titles,creators"}
    return [_datacite_work(record["attributes"]) for record in _answer(DATACITE_URL, query)["data"]]


def openalex_works(title: str) -> list[Work]:
    """Return the OpenAlex records whose title holds the words of a title in their order, the best matches first.

    A search costs a part of the daily budget of the caller, which is ten times larger with the free key in
    OPENALEX_KEY. OpenAlex answers a request beyond the budget with an error."""
    query = {"filter": f'title.search:"{_words(title)}"', "per-page": RECORDS, "select": "title,authorships"}
    if os.environ.get("OPENALEX_KEY"):
        query["api_key"] = os.environ["OPENALEX_KEY"]
    return [Work(record.get("title") or "", tuple(name for author in record["authorships"]
                                                  if (name := (author.get("author") or {}).get("display_name"))))
            for record in _answer(OPENALEX_URL, query)["results"]]


def openreview_works(title: str) -> list[Work]:
    """Return the papers on OpenReview whose titles are the closest to a title, the best matches first.

    OpenReview holds the papers of venues such as ICLR and ICML months before a database lists them. It answers 20
    requests a minute, therefore a further request waits, and it names no author of a paper under review."""
    OPENREVIEW_PACE.wait()
    query = {"term": _words(title), "type": "terms", "content": "title", "source": "forum", "limit": RECORDS}
    return [_openreview_work(note["content"]) for note in _answer(OPENREVIEW_URL, query)["notes"]]


def _datacite_work(attributes: dict) -> Work:
    titles = attributes.get("titles") or [{}]
    # A record without the two parts of a name gives the name of a person with the family name first, before a comma.
    names = [" ".join(filter(None, (creator.get("givenName"), creator.get("familyName"))))
             or " ".join(reversed((creator.get("name") or "").split(", ", 1)))
             for creator in attributes.get("creators") or ()]
    return Work(titles[0].get("title") or "", tuple(name for name in names if name))


def _crossref_work(record: dict) -> Work:
    title, subtitle = (html.unescape(MARKUP.sub("", (record.get(key) or [""])[0])) for key in ("title", "subtitle"))
    # Some publishers register the part of a title after its colon as a subtitle.
    if subtitle and subtitle.lower() not in title.lower():
        title = f"{title}: {subtitle}"
    names = [" ".join(filter(None, (author.get("given"), author.get("family")))) or author.get("name") or ""
             for author in record.get("author") or ()]
    return Work(title, tuple(name for name in names if name), record.get("type") in CONTAINERS)


def _openreview_work(content: dict) -> Work:
    title, authors = ((content.get(field) or {}).get("value") for field in ("title", "authors"))
    # A note names an author by a plain name or in a record with the full name.
    names = [author.get("fullname") if isinstance(author, dict) else author for author in authors or ()]
    return Work(title or "", tuple(name for name in names if name))


def _words(title: str) -> str:
    """Return a title as words alone, since a quote, a comma, or a colon has a meaning in a query."""
    return " ".join(NOT_WORD.sub(" ", title).split())


def _answer(url: str, query: dict) -> dict | list:
    """Return the JSON answer of a service. A request that the service turns away with a short time to wait goes out
    once more after that time, as OpenAlex asks of a client that it paces."""
    address = f"{url}?{urllib.parse.urlencode(query)}" if query else url
    request = urllib.request.Request(address, headers={"User-Agent": "PeerCheck"})
    try:
        return _json(request)
    except urllib.error.HTTPError as refusal:
        wait = refusal.headers.get("Retry-After") or ""
        if refusal.code not in COME_BACK or not wait.isdigit() or int(wait) > LONGEST_WAIT:
            raise
    time.sleep(int(wait))
    return _json(request)


def _json(request: urllib.request.Request) -> dict | list:
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return json.load(response)

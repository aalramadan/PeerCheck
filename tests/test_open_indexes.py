"""Tests of the lookups in DataCite, Crossref, OpenAlex, and OpenReview, on answers that the services gave and a
local server.

datacite-dois.json answers for two arXiv DOIs and crossref-dois.json for three DOIs of publishers. doi-agencies.json
answers for six DOIs of five registration agencies and one DOI that does not exist. datacite-title.json,
openalex-title.json, and openreview-title.json each answer for one title, the last one cut to the fields that
PeerCheck reads.
"""

from __future__ import annotations

import json
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from peercheck.papers import open_indexes
from peercheck.papers.open_indexes import Work

FIXTURES = Path(__file__).parent / "fixtures" / "open-indexes"
VASWANI = ("Ashish Vaswani", "Noam Shazeer", "Niki Parmar", "Jakob Uszkoreit", "Llion Jones", "Aidan N. Gomez",
           "Lukasz Kaiser", "Illia Polosukhin")


class Service:
    """Answers each request from the next given fixture or value and keeps the requests that were made."""

    def __init__(self):
        self.answers: list = []
        self.requests: list[tuple[str, dict]] = []

    def __call__(self, url, query):
        self.requests.append((url, query))
        given = self.answers.pop(0)
        return json.loads((FIXTURES / given).read_text(encoding="utf-8")) if isinstance(given, str) else given


@pytest.fixture
def service(monkeypatch):
    """A stand-in for the services, in an environment without the key of OpenAlex and the address for Crossref."""
    fake = Service()
    monkeypatch.setattr(open_indexes, "_answer", fake)
    for name in ("OPENREVIEW_PACE", "CROSSREF_PACE"):
        pace = getattr(open_indexes, name)
        monkeypatch.setattr(open_indexes, name, open_indexes.Pace(pace.times.maxlen, pace.window))
    monkeypatch.delenv("OPENALEX_KEY", raising=False)
    monkeypatch.delenv("CROSSREF_MAILTO", raising=False)
    return fake


@pytest.fixture
def server(monkeypatch):
    """A local server in place of DataCite that answers with the body and the status of the test, after it has
    turned as many requests away for a time, with the status of a refusal, as the test says. It may announce a
    longer body than it sends."""
    class Handler(BaseHTTPRequestHandler):
        body, status, seen, refusals, refusal, retry_after, announced = b"{}", 200, [], 0, 429, "2", None

        def do_GET(self):
            self.seen.append((self.path, self.headers.get("User-Agent")))
            if Handler.refusals:
                Handler.refusals -= 1
                self.send_response(self.refusal)
                self.send_header("Retry-After", self.retry_after)
                self.end_headers()
                return
            self.send_response(self.status)
            if self.announced:
                self.send_header("Content-Length", str(self.announced))
            self.end_headers()
            self.wfile.write(self.body)

        def log_message(self, *args):
            pass

    running = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=running.serve_forever, daemon=True).start()
    monkeypatch.setattr(open_indexes, "DATACITE_URL", f"http://127.0.0.1:{running.server_port}/dois")
    yield Handler
    running.shutdown()


def test_datacite_doi_works_returns_the_record_of_each_doi_in_lower_case(service):
    service.answers.append("datacite-dois.json")
    works = open_indexes.datacite_doi_works(["10.48550/arxiv.1207.7214", "10.48550/arxiv.1706.03762",
                                             "10.48550/arxiv.0000.00000"])
    assert works == {
        "10.48550/arxiv.1706.03762": Work("Attention Is All You Need", VASWANI),
        "10.48550/arxiv.1207.7214": Work("Observation of a new particle in the search for the Standard Model Higgs "
                                         "boson with the ATLAS detector at the LHC", ("The ATLAS Collaboration",))}


def test_datacite_doi_works_returns_a_doi_in_lower_case_whatever_the_case_of_the_answer(service):
    service.answers.append({"data": [{"id": "10.5555/ZENODO.1", "attributes": {"titles": [{"title": "A made-up title"}],
                                                                               "creators": [{"name": "Quill, Ada"}]}}]})
    assert open_indexes.datacite_doi_works(["10.5555/zenodo.1"]) == {
        "10.5555/zenodo.1": Work("A made-up title", ("Ada Quill",))}


def test_datacite_doi_works_asks_for_all_dois_in_one_request_and_only_for_titles_and_creators(service):
    service.answers.append({"data": []})
    open_indexes.datacite_doi_works(["10.48550/arXiv.1207.7214", "10.5281/zenodo.0000000"])
    assert service.requests == [(open_indexes.DATACITE_URL, {
        "query": 'doi:("10.48550/arxiv.1207.7214" OR "10.5281/zenodo.0000000")', "page[size]": 50,
        "fields[dois]": "titles,creators"})]


def test_datacite_doi_works_leaves_out_a_doi_that_would_end_the_quoted_query(service):
    assert open_indexes.datacite_doi_works(['10.5555/a"b', "10.5555/a\\b"]) == {}
    assert service.requests == []


def test_crossref_doi_works_returns_the_record_of_each_doi_in_lower_case(service):
    service.answers.append("crossref-dois.json")
    works = open_indexes.crossref_doi_works(["10.1093/biomet/26.4.404", "10.1145/3180155.3180167",
                                             "10.1007/978-3-031-73143-3_7", "10.5555/0000000.0000000"])
    assert works == {
        "10.1093/biomet/26.4.404": Work(
            "THE USE OF CONFIDENCE OR FIDUCIAL LIMITS ILLUSTRATED IN THE CASE OF THE BINOMIAL",
            ("C. J. CLOPPER", "E. S. PEARSON")),
        "10.1145/3180155.3180167": Work("Deep code search", ("Xiaodong Gu", "Hongyu Zhang", "Sunghun Kim")),
        "10.1007/978-3-031-73143-3_7": Work("Automated Requirements Relations Extraction",
                                            ("Quim Motger", "Xavier Franch"))}


def test_crossref_doi_works_asks_for_all_dois_in_one_request_and_only_for_titles_authors_and_the_type(service):
    service.answers.append({"message": {"items": []}})
    open_indexes.crossref_doi_works(["10.1093/Biomet/26.4.404", "10.1145/3180155.3180167"])
    assert service.requests == [(open_indexes.CROSSREF_URL, {
        "filter": "doi:10.1093/biomet/26.4.404,doi:10.1145/3180155.3180167", "rows": 50,
        "select": "DOI,title,subtitle,author,type"})]


def test_crossref_gets_one_request_at_once_and_the_next_one_after_the_rest_of_its_second(service, monkeypatch):
    clock, waits = [1000.0], []

    def sleep(seconds):
        waits.append(seconds)
        clock[0] += seconds

    monkeypatch.setattr(open_indexes.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(open_indexes.time, "sleep", sleep)
    service.answers.extend([{"message": {"items": []}}] * 3)
    open_indexes.crossref_doi_works(["10.5555/1"])
    assert waits == []
    clock[0] += 0.25
    open_indexes.crossref_doi_works(["10.5555/2"])
    clock[0] += 5.0
    open_indexes.crossref_doi_works(["10.5555/3"])
    assert waits == [0.75, 0.0]


def test_crossref_doi_works_leaves_out_a_doi_that_would_end_the_filter(service):
    assert open_indexes.crossref_doi_works(["10.5555/a,b"]) == {}
    assert service.requests == []


def test_crossref_doi_works_names_the_address_of_the_user_when_it_is_set(service, monkeypatch):
    monkeypatch.setenv("CROSSREF_MAILTO", "chair@example.org")
    service.answers.append({"message": {"items": []}})
    open_indexes.crossref_doi_works(["10.5555/1"])
    assert service.requests[0][1]["mailto"] == "chair@example.org"


def test_crossref_record_joins_a_subtitle_and_reads_markup_as_plain_text(service):
    service.answers.append({"message": {"items": [
        {"DOI": "10.5555/A1", "title": ["A <i>made-up</i> title on patches &amp; ports"], "subtitle": ["A field study"],
         "author": [{"given": "Ada", "family": "Quill"}, {"name": "Made-up Project"}, {}]},
        {"DOI": "10.5555/2", "title": ["A made-up title: A field study"], "subtitle": ["A Field Study"]},
        {"DOI": "10.5555/3"}]}})
    assert open_indexes.crossref_doi_works(["10.5555/A1", "10.5555/2", "10.5555/3"]) == {
        "10.5555/a1": Work("A made-up title on patches & ports: A field study", ("Ada Quill", "Made-up Project")),
        "10.5555/2": Work("A made-up title: A field study", ()),
        "10.5555/3": Work("", ())}


@pytest.mark.parametrize(("kind", "container"), [
    ("proceedings", True), ("journal", True), ("journal-issue", True), ("book", True), ("book-series", True),
    ("proceedings-article", False), ("journal-article", False), ("book-chapter", False), ("posted-content", False),
    (None, False)])
def test_crossref_record_of_a_whole_publication_is_a_container(service, kind, container):
    record = {"DOI": "10.5555/1", "title": ["Proceedings of a Made-up Meeting on Patches"], "type": kind}
    service.answers.append({"message": {"items": [record]}})
    assert open_indexes.crossref_doi_works(["10.5555/1"])["10.5555/1"].container is container


def test_doi_agencies_returns_the_agency_of_each_doi_that_exists(service):
    service.answers.append("doi-agencies.json")
    agencies = open_indexes.doi_agencies([
        "10.11999/JEIT250048", "10.1145/3180155.3180167", "10.48550/arxiv.1706.03762", "10.5555/does-not-exist-0000",
        "10.11499/sicejl.60.1", "10.3745/kipsta.2012.19a.1.001", "10.1400/187294"])
    assert agencies == {
        "10.11999/jeit250048": "ISTIC", "10.1145/3180155.3180167": "Crossref", "10.48550/arxiv.1706.03762": "DataCite",
        "10.11499/sicejl.60.1": "JaLC", "10.3745/kipsta.2012.19a.1.001": "KISTI", "10.1400/187294": "mEDRA"}


def test_doi_agencies_returns_a_doi_in_lower_case_whatever_the_case_of_the_answer(service):
    service.answers.append([{"DOI": "10.5555/A1", "RA": "ISTIC"}])
    assert open_indexes.doi_agencies(["10.5555/a1"]) == {"10.5555/a1": "ISTIC"}


def test_doi_agencies_asks_for_all_dois_in_one_request_with_the_marks_of_a_doi_escaped(service):
    service.answers.append([])
    open_indexes.doi_agencies(["10.1002/(SICI)1097-0258(19980430)17:8<857::AID-SIM777>3.0.CO;2-E", "10.5555/A1"])
    asked = "10.1002/%28sici%291097-0258%2819980430%2917%3A8%3C857%3A%3Aaid-sim777%3E3.0.co%3B2-e,10.5555/a1"
    assert service.requests == [(f"{open_indexes.DOI_AGENCY_URL}/{asked}", {})]


def test_doi_agencies_leaves_out_a_doi_that_would_end_the_doi_in_the_address(service):
    assert open_indexes.doi_agencies(["10.5555/a,b"]) == {}
    assert service.requests == []


def test_datacite_works_asks_for_the_words_of_the_title_as_a_phrase_with_the_best_matches_first(service):
    service.answers.append("datacite-title.json")
    works = open_indexes.datacite_works("“Attention” is all: you need!")
    assert service.requests == [(open_indexes.DATACITE_URL, {
        "query": 'titles.title:"Attention is all you need"', "sort": "relevance", "page[size]": 10,
        "fields[dois]": "titles,creators"})]
    assert len(works) == 10 and Work("Attention Is All You Need", VASWANI) in works


def test_datacite_record_without_a_title_or_a_name_gives_empty_fields(service):
    service.answers.append({"data": [{"id": "10.5555/1", "attributes": {"titles": [], "creators": [
        {"name": "Made-up Project"}, {"givenName": "Ada", "familyName": "Quill"}, {}]}}]})
    assert open_indexes.datacite_works("A made-up title") == [Work("", ("Made-up Project", "Ada Quill"))]


def test_datacite_name_with_the_family_name_first_is_read_with_the_family_name_last(service):
    creators = [{"name": "Quill, Ada"}, {"name": "Reed, Ben", "givenName": "Benjamin", "familyName": "Reed"}]
    service.answers.append({"data": [{"id": "10.5555/1", "attributes": {"titles": [{"title": "A made-up title"}],
                                                                        "creators": creators}}]})
    assert open_indexes.datacite_works("A made-up title") == [Work("A made-up title", ("Ada Quill", "Benjamin Reed"))]


def test_openalex_works_returns_the_title_and_the_authors_of_each_record(service):
    service.answers.append("openalex-title.json")
    works = open_indexes.openalex_works("Attention Is All You Need")
    assert service.requests == [(open_indexes.OPENALEX_URL, {
        "filter": 'title.search:"Attention Is All You Need"', "per-page": 10, "select": "title,authorships"})]
    assert works[0] == Work("Attention Is All You Need", (*VASWANI[:6], "Łukasz Kaiser", "Illia Polosukhin"))
    assert len(works) == 5


def test_openalex_works_asks_for_the_words_of_the_title_alone(service):
    service.answers.append({"results": []})
    open_indexes.openalex_works("“A made-up title”: on patches, ports & “quotes”")
    assert service.requests[0][1]["filter"] == 'title.search:"A made up title on patches ports quotes"'


def test_openalex_author_without_a_name_is_left_out(service):
    authorships = [{"author": {"display_name": "Ada Quill"}}, {"author": {"display_name": None}}, {"author": None}, {}]
    service.answers.append({"results": [{"title": "A made-up title", "authorships": authorships}]})
    assert open_indexes.openalex_works("A made-up title") == [Work("A made-up title", ("Ada Quill",))]


def test_openalex_works_sends_the_key_of_the_user_when_it_is_set(service, monkeypatch):
    monkeypatch.setenv("OPENALEX_KEY", "not-a-real-key")
    service.answers.append({"results": []})
    open_indexes.openalex_works("A made-up title")
    assert service.requests[0][1]["api_key"] == "not-a-real-key"


def test_openreview_works_returns_the_title_and_the_authors_of_each_paper(service):
    service.answers.append("openreview-title.json")
    works = open_indexes.openreview_works("PADA-Coder: Improving Plan-Following Code Generation")
    assert service.requests == [(open_indexes.OPENREVIEW_URL, {
        "term": "PADA Coder Improving Plan Following Code Generation", "type": "terms", "content": "title",
        "source": "forum", "limit": 10})]
    assert works[0] == Work("PADA-Coder: Improving Plan-Following Code Generation via Perturbation-Verified Attention "
                            "Distillation and Dynamic Alignment",
                            ("Yihong Huang", "Ke Qin", "Rongzheng Wang", "Muquan Li", "Jiakai Li", "Xiurui Xie",
                             "Shuang Liang"))
    assert works[2].authors[:2] == ("Xue Jiang", "Yihong Dong")
    assert len(works) == 3


def test_openreview_paper_under_review_names_no_author_and_a_note_without_fields_gives_empty_ones(service):
    service.answers.append({"notes": [{"content": {"title": {"value": "A made-up title under review"}}},
                                      {"content": {}}]})
    assert open_indexes.openreview_works("A made-up title") == [Work("A made-up title under review", ()), Work("", ())]


def test_openreview_author_without_a_name_is_left_out(service):
    authors = [{"fullname": "Ada Quill", "username": "~Ada_Quill1"}, {"fullname": "", "username": ""}, "", "Ben Reed"]
    service.answers.append({"notes": [{"content": {"title": {"value": "A made-up title"},
                                                   "authors": {"value": authors}}}]})
    assert open_indexes.openreview_works("A made-up title") == [Work("A made-up title", ("Ada Quill", "Ben Reed"))]


def test_openreview_gets_20_requests_at_once_and_the_next_one_after_the_rest_of_its_minute(service, monkeypatch):
    clock, waits = [1000.0], []

    def sleep(seconds):
        waits.append(seconds)
        clock[0] += seconds

    monkeypatch.setattr(open_indexes.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(open_indexes.time, "sleep", sleep)
    service.answers.extend([{"notes": []}] * 22)
    for _request in range(20):
        open_indexes.openreview_works("A made-up title")
        clock[0] += 0.5
    assert waits == []
    open_indexes.openreview_works("A made-up title")
    open_indexes.openreview_works("A made-up title")
    assert waits == [52.0, 0.5]


def test_pace_lets_a_request_pass_at_once_after_a_quiet_window(monkeypatch):
    clock, waits = [1000.0], []
    monkeypatch.setattr(open_indexes.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(open_indexes.time, "sleep", waits.append)
    pace = open_indexes.Pace(2, 10.0)
    pace.wait()
    pace.wait()
    clock[0] += 30.0
    pace.wait()
    assert waits == [0.0]


def test_budget_is_spent_once_its_seconds_are_over(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(open_indexes.time, "monotonic", lambda: clock[0])
    budget = open_indexes.Budget(30.0)
    clock[0] += 29.0
    assert not budget.is_spent()
    clock[0] += 1.0
    assert budget.is_spent()


def test_pace_lets_one_request_at_a_time_decide_on_its_wait(monkeypatch):
    waiting, second_wait, go_on = threading.Event(), threading.Event(), threading.Event()

    def sleep(seconds):
        (second_wait if waiting.is_set() else waiting).set()
        go_on.wait(60)

    monkeypatch.setattr(open_indexes.time, "sleep", sleep)
    pace = open_indexes.Pace(1, 60.0)
    pace.wait()
    requests = [threading.Thread(target=pace.wait, daemon=True) for _request in range(2)]
    for request in requests:
        request.start()
    assert waiting.wait(60) and not second_wait.wait(0.3)
    go_on.set()
    for request in requests:
        request.join(60)


@pytest.mark.parametrize("answer", [
    {"error": "made-up message of a service"}, ["made-up message of a service"],
    {"results": [{"title": "A made-up title", "authorships": None}]},
    {"results": [{"title": "A made-up title", "authorships": ["Ada Quill"]}]}, {"results": [None]}])
def test_answer_in_another_form_raises_a_lookup_error(service, answer):
    service.answers.append(answer)
    with pytest.raises(open_indexes.LOOKUP_ERRORS):
        open_indexes.openalex_works("A made-up title")


def test_request_names_peercheck_and_carries_the_query(server):
    server.body = json.dumps({"data": []}).encode()
    assert open_indexes.datacite_works("A made-up title") == []
    [(path, agent)] = server.seen
    assert agent == "PeerCheck"
    assert urllib.parse.parse_qs(urllib.parse.urlsplit(path).query)["query"] == ['titles.title:"A made up title"']


def test_request_without_a_query_ends_at_its_path(server, monkeypatch):
    monkeypatch.setattr(open_indexes, "DOI_AGENCY_URL", open_indexes.DATACITE_URL.replace("/dois", "/doiRA"))
    server.body = b"[]"
    assert open_indexes.doi_agencies(["10.5555/1"]) == {}
    assert [path for path, _agent in server.seen] == ["/doiRA/10.5555/1"]


@pytest.mark.parametrize("refusal", [429, 503])
def test_request_that_a_service_turns_away_for_a_short_time_goes_out_once_more_after_that_time(server, monkeypatch,
                                                                                               refusal):
    waits = []
    monkeypatch.setattr(open_indexes.time, "sleep", waits.append)
    server.body, server.refusals, server.refusal = json.dumps({"data": []}).encode(), 1, refusal
    assert open_indexes.datacite_works("A made-up title") == []
    assert (waits, len(server.seen)) == ([2], 2)


@pytest.mark.parametrize("failure", [400, 403, 404, 500, 502])
def test_request_that_fails_with_a_status_that_asks_for_no_later_request_does_not_go_out_again(server, monkeypatch,
                                                                                               failure):
    waits = []
    monkeypatch.setattr(open_indexes.time, "sleep", waits.append)
    server.refusals, server.refusal = 1, failure
    with pytest.raises(open_indexes.LOOKUP_ERRORS):
        open_indexes.datacite_works("A made-up title")
    assert (waits, len(server.seen)) == ([], 1)


def test_request_that_a_service_turns_away_twice_raises_a_lookup_error(server, monkeypatch):
    monkeypatch.setattr(open_indexes.time, "sleep", lambda seconds: None)
    server.refusals = 2
    with pytest.raises(open_indexes.LOOKUP_ERRORS):
        open_indexes.datacite_works("A made-up title")
    assert len(server.seen) == 2


def test_request_that_a_service_turns_away_for_a_long_time_does_not_go_out_again(server, monkeypatch):
    waits = []
    monkeypatch.setattr(open_indexes.time, "sleep", waits.append)
    server.refusals, server.retry_after = 1, "600"
    with pytest.raises(open_indexes.LOOKUP_ERRORS):
        open_indexes.datacite_works("A made-up title")
    assert (waits, len(server.seen)) == ([], 1)


def test_answer_that_is_no_json_raises_a_lookup_error(server):
    server.body = b"<html>A made-up page that asks whether the client is a person</html>"
    with pytest.raises(open_indexes.LOOKUP_ERRORS):
        open_indexes.datacite_works("A made-up title")


def test_refused_request_that_names_no_time_raises_a_lookup_error_and_does_not_go_out_again(server, monkeypatch):
    waits = []
    monkeypatch.setattr(open_indexes.time, "sleep", waits.append)
    server.status = 429
    with pytest.raises(open_indexes.LOOKUP_ERRORS):
        open_indexes.datacite_works("A made-up title")
    assert (waits, len(server.seen)) == ([], 1)


def test_request_waits_at_most_the_timeout_for_its_answer(monkeypatch):
    waits = []

    def urlopen(request, timeout=None):
        waits.append(timeout)
        raise OSError("made-up outage")

    monkeypatch.setattr(open_indexes.urllib.request, "urlopen", urlopen)
    with pytest.raises(OSError, match="made-up outage"):
        open_indexes.datacite_works("A made-up title")
    assert waits == [open_indexes.TIMEOUT] and open_indexes.TIMEOUT == 20


def test_answer_that_ends_early_raises_a_lookup_error(server):
    server.body, server.announced = b'{"data": [', 4000
    with pytest.raises(open_indexes.LOOKUP_ERRORS):
        open_indexes.datacite_works("A made-up title")

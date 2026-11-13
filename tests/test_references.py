"""Tests of the reference check, which replay recorded output of Hallucinator 0.2.4 in place of the binary.

The fixtures come from real runs. offline-run.json is the offline run on sample-paper.pdf, built from
sample-paper.tex, with ten real references and three fabricated ones. online-run.json is the local run with DOI
lookups on online-sample.tex, and online-titles-run.json the online run on online-lookups.bib, which holds its two
open references, with each author list cut to three names. broken-pdf.stderr is the error output on a file that is
no PDF. Stand-ins answer for DataCite, Crossref, doi.org, OpenAlex, and OpenReview, since no test reaches the network.
"""

from __future__ import annotations

import contextlib
import dataclasses
import datetime
import http.client
import json
import sqlite3
import subprocess
import types
from pathlib import Path

import pymupdf
import pytest

from peercheck import profile as profile_module
from peercheck.findings import Severity
from peercheck.models import Paper
from peercheck.papers import reference_setup, references
from peercheck.papers.lookup_cache import LookupCache
from peercheck.papers.open_indexes import Work

FIXTURES = Path(__file__).parent / "fixtures" / "references"
SPLIT_PDF = Path(__file__).parent / "fixtures" / "reference-list" / "ieee-split-entries.pdf"
TITLE = "A made-up title on the porting of patches"
ENTRY = f"A. Quill and B. Reed, “{TITLE},” in Proc. Int. Conf. Softw. Eng., 2021, pp. 101–112."
ATLAS = ("Observation of a new particle in the search for the Standard Model Higgs boson with the ATLAS detector at "
         "the LHC")
BOOK = {"title": "Maintaining Stable Releases: A Field Guide", "ref_authors": ["P. Zeller"],
        "raw_citation": "P. Zeller, Maintaining Stable Releases: A Field Guide. Springfield: Meadow Press, 2019."}
# Hallucinator looks up a title of fewer than four words only when its entry gives an identifier.
SHORT = {"title": "Deep patch search", "ref_authors": ["A. Quill"],
         "raw_citation": "A. Quill, “Deep patch search,” in Proc. Int. Conf. Softw. Eng., 2021, doi: 10.5555/1."}
OTHER_AUTHORS = {"status": "mismatch", "source": "DBLP", "found_authors": ["Petra Zeller", "Hana Novak"],
                 "db_results": [{"db": "DBLP", "status": "author_mismatch"}]}
ACCEPTED_FOR_ONE_AUTHOR = {
    "status": "verified", "source": "DBLP", "ref_authors": ["A. Quill", "T. Brennan", "K. Ito"],
    "found_authors": ["Ada Quill", "Petra Zeller", "Hana Novak"], "paper_url": "https://dblp.org/rec/conf/made-up/1",
    "raw_citation": ENTRY.replace("A. Quill and B. Reed", "A. Quill, T. Brennan, and K. Ito"),
    "db_results": [{"db": "DBLP", "status": "match"}]}
DOI = "10.5555/3377811.3380362"
WITH_DOI = {"raw_citation": f"{ENTRY[:-1]}, doi: {DOI}."}
OTHER_WORK = Work("Another made-up title on flaky builds", ("Petra Zeller", "Hana Novak"))
FOUND = {"status": "verified", "source": "CrossRef", "found_authors": ["Ada Quill", "Ben Reed"],
         "db_results": [{"db": "CrossRef", "status": "match"}]}
QUESTION = {"title": "Do stable branches receive the fixes they need?” in Proc",
            "ref_authors": ["C. Marsh", "D. Okafor", "E. Lindqvist"],
            "raw_citation": "C. Marsh, D. Okafor, and E. Lindqvist, “Do stable branches receive the fixes they need?” "
                            "in Proc. Int. Conf. Softw. Eng., 2022, pp. 44–55."}


class FakeHallucinator:
    """Replays reports, each a fixture name or loaded JSON, and keeps each command and environment.

    A report without a name goes to the next run. A named report goes to the run that writes the report of that
    name, such as paper-7 for the local run on paper 7 and online for the online run. An exception is raised in
    place of its run. An online run without a report answers that CrossRef holds none of its titles."""

    def __init__(self, *reports, returncode: int = 0, stderr: str = "", named: dict | None = None):
        self.reports = list(reports)
        self.named = named or {}
        self.returncode = returncode
        self.stderr = stderr
        self.calls: list[tuple[list[str], dict]] = []

    def __call__(self, command, **kwargs):
        self.calls.append((list(command), kwargs))
        target = Path(command[command.index("--json") + 1])
        report = self.named[target.stem] if target.stem in self.named else self.reports.pop(0) if self.reports else None
        if isinstance(report, Exception):
            raise report
        if report is None and "--cache-path" in command:
            sent = [line.split("{", 1)[1].removesuffix("},") for line in Path(command[-1]).read_text(
                encoding="utf-8").splitlines() if line.startswith("  title = ")]
            report = [{"references": [{"original_number": number, "title": title, "status": "not_found",
                                       "db_results": [{"db": "CrossRef", "status": "no_match"}]}
                                      for number, title in enumerate(sent, start=1)]}]
        if report:
            text = (FIXTURES / report).read_text(encoding="utf-8") if isinstance(report, str) else json.dumps(report)
            target.write_text(text, encoding="utf-8")
        return subprocess.CompletedProcess(command, self.returncode, "", self.stderr)

    def disabled(self, call: int = 0) -> list[str]:
        command = self.calls[call][0]
        return command[command.index("--disable-dbs") + 1].split(",") if "--disable-dbs" in command else []


class FakeIndexes:
    """Stands in for the open indexes with the records that a test gives and keeps what each one was asked.

    dois and crossref_dois hold the records of DataCite and of Crossref by DOI, and agencies the registration agency
    of a DOI. The other three hold records by the title that an index is asked for."""

    def __init__(self):
        self.dois: dict[str, Work] = {}
        self.crossref_dois: dict[str, Work] = {}
        self.agencies: dict[str, str] = {}
        self.datacite: dict[str, list[Work]] = {}
        self.openalex: dict[str, list[Work]] = {}
        self.openreview: dict[str, list[Work]] = {}
        self.asked: dict[str, list] = {"dois": [], "crossref_dois": [], "agencies": [], "datacite": [], "openalex": [],
                                       "openreview": []}
        self.down: set[str] = set()

    def doi_agencies(self, dois):
        return self._answer("agencies", list(dois), {doi: self.agencies[doi] for doi in dois if doi in self.agencies})

    def datacite_doi_works(self, dois):
        return self._answer("dois", list(dois), {doi: self.dois[doi] for doi in dois if doi in self.dois})

    def crossref_doi_works(self, dois):
        return self._answer("crossref_dois", list(dois),
                            {doi: self.crossref_dois[doi] for doi in dois if doi in self.crossref_dois})

    def datacite_works(self, title):
        return self._answer("datacite", title, self.datacite.get(title, []))

    def openalex_works(self, title):
        return self._answer("openalex", title, self.openalex.get(title, []))

    def openreview_works(self, title):
        return self._answer("openreview", title, self.openreview.get(title, []))

    def nothing_asked(self) -> bool:
        return not any(self.asked.values())

    def _answer(self, index, question, answer):
        self.asked[index].append(question)
        if index in self.down:
            raise OSError("made-up outage")
        return answer


@pytest.fixture(autouse=True)
def indexes(monkeypatch):
    """Open indexes that hold no work until a test adds one, and an environment without the keys of the sources."""
    fake = FakeIndexes()
    for name in ("datacite_doi_works", "crossref_doi_works", "doi_agencies", "datacite_works", "openalex_works",
                 "openreview_works"):
        monkeypatch.setattr(references.open_indexes, name, getattr(fake, name))
    for name in ("S2_API_KEY", "CROSSREF_MAILTO", "OPENALEX_KEY"):
        monkeypatch.delenv(name, raising=False)
    return fake


@pytest.fixture
def cache(tmp_path):
    """A cache with a stand-in binary, a stand-in DBLP database, and the tiny Retraction Watch CSV."""
    folder = tmp_path / "cache" / "hallucinator"
    (folder / reference_setup.VERSION).mkdir(parents=True)
    (folder / reference_setup.VERSION / "hallucinator-cli").write_text("", encoding="utf-8")
    (folder / "dblp.db").write_text("", encoding="utf-8")
    (tmp_path / "cache" / "retraction_watch.csv").write_bytes((FIXTURES / "retraction_watch.csv").read_bytes())
    return tmp_path / "cache"


def profile_with(cache, **options):
    profile = profile_module.load("icse-2027")
    return dataclasses.replace(profile, checks={**profile.checks, "references": {"cache": str(cache), **options}})


def run(tmp_path, cache, fake, monkeypatch, pdf=None, **options):
    monkeypatch.setattr(references.subprocess, "run", fake)
    monkeypatch.setattr(reference_setup.platform, "system", lambda: "Linux")
    paper = Paper(paper_id=7, pdf=pdf or tmp_path / "paper.pdf")
    return references.check_batch([paper], profile_with(cache, **options), tmp_path / "work")[7]


def by_check(findings, check):
    return [f for f in findings if f.check == check]


def report(*entries: dict) -> list:
    """Return a report whose references DBLP does not hold, each with the fields that a test gives."""
    return [{"references": [
        {"original_number": number, "title": TITLE, "raw_citation": ENTRY, "status": "not_found",
         "ref_authors": ["A. Quill", "B. Reed"], "db_results": [{"db": "DBLP", "status": "no_match"}], **entry}
        for number, entry in enumerate(entries, start=1)]}]


def parsed(**entry) -> references.Reference:
    return references.parse_report(report(entry))[0]


def dblp_database(cache, *records: tuple[str, list[str]]) -> None:
    """Write a DBLP database in the layout of Hallucinator with the given records, each a title and its authors."""
    path = cache / "hallucinator" / "dblp.db"
    path.unlink()
    with contextlib.closing(sqlite3.connect(path)) as database:
        database.executescript(
            "create table authors (id integer primary key, name text unique not null);"
            "create table publications (id integer primary key, key text unique not null, title text not null);"
            "create table publication_authors (pub_id integer not null, author_id integer not null,"
            " primary key (pub_id, author_id));"
            "create virtual table publications_fts using fts5(title, content='publications', content_rowid='id');")
        for number, (title, names) in enumerate(records, start=1):
            database.execute("insert into publications values (?, ?, ?)", (number, f"conf/made-up/{number}", title))
            database.execute("insert into publications_fts (rowid, title) values (?, ?)", (number, title))
            for name in names:
                database.execute("insert or ignore into authors (name) values (?)", (name,))
                database.execute("insert into publication_authors select ?, id from authors where name = ?",
                                 (number, name))
        database.commit()


def test_offline_run_reports_fabricated_references_as_not_found(tmp_path, cache, monkeypatch):
    findings = run(tmp_path, cache, FakeHallucinator("offline-run.json"), monkeypatch, online=False)
    missing = by_check(findings, "references.not-found")
    assert [f.message.split('"')[0] for f in missing] == ["Reference [11] ", "Reference [13] "]
    assert all(f.severity is Severity.WARNING and f.message.endswith("was not found in DBLP") for f in missing)


def test_offline_run_reports_a_real_title_with_false_authors_as_author_mismatch(tmp_path, cache, monkeypatch):
    findings = run(tmp_path, cache, FakeHallucinator("offline-run.json"), monkeypatch, online=False)
    [mismatch] = by_check(findings, "references.author-mismatch")
    assert mismatch.message.startswith('Reference [12] "Automatically finding patches using genetic programming"')
    assert "Claire Le Goues" in mismatch.message
    assert mismatch.evidence.startswith("T. Brennan, K. Ito, and S. Malhotra")


def test_offline_run_reports_a_cited_work_with_a_retraction_notice(tmp_path, cache, monkeypatch):
    findings = run(tmp_path, cache, FakeHallucinator("offline-run.json"), monkeypatch, online=False)
    [retracted] = by_check(findings, "references.retracted")
    assert retracted.severity is Severity.WARNING
    assert retracted.message.startswith("Reference [10] ")
    assert retracted.message.endswith("Retraction of 2008-04-03")
    assert retracted.evidence == "DOI 10.1109/aswec.2008.4483193. Reason: Euphemisms for Plagiarism"


def test_evidence_holds_at_most_200_characters_of_the_reference_text(tmp_path, cache, monkeypatch):
    findings = run(tmp_path, cache, FakeHallucinator("offline-run.json"), monkeypatch, online=False)
    [first, *_] = by_check(findings, "references.not-found")
    assert len(first.evidence) <= 200
    assert first.evidence.startswith("M. Hartmann, P. Venkataraman, and L. Oberg")
    assert first.evidence.endswith("...")


def test_summary_counts_the_references_of_the_run(tmp_path, cache, monkeypatch):
    findings = run(tmp_path, cache, FakeHallucinator("offline-run.json"), monkeypatch, online=False)
    [summary] = by_check(findings, "references.summary")
    assert summary.severity is Severity.INFO
    assert summary.message == ("13 references checked offline: 10 found, 2 not found, 1 with other authors or "
                               "identifiers, 0 not looked up")


def test_local_run_gets_the_reference_list_as_a_pdf_with_one_line_per_entry(tmp_path, cache, monkeypatch):
    fake = FakeHallucinator("offline-run.json")
    run(tmp_path, cache, fake, monkeypatch, pdf=SPLIT_PDF, online=False)
    source = Path(fake.calls[0][0][-1])
    assert source == tmp_path / "work" / "references" / "paper-7-list.pdf"
    with pymupdf.open(source) as document:
        lines = document[0].get_text().splitlines()
    assert lines[:2] == ["Reference list", "References"]
    assert len(lines) == 76
    assert lines[5] == ("[4] H. Novak, “Merge conflicts in cherry-picked commits and their resolution by maintainers "
                        "of open source projects, with supplementary material on the conflicts of 40 projects,” "
                        "Empirical Softw. Eng., vol. 28, no. 3, pp. 1–34, 2023.")


def test_printable_text_holds_plain_letters_and_a_space_for_each_character_that_the_list_font_lacks():
    odd = "Eﬃcient port\u00ading\x07of\ud83dpatches\U0001f600and\ufffdfixes"
    assert references._printable(odd) == "Efficient porting of patches and fixes"


def test_list_pdf_holds_an_entry_with_characters_that_no_pdf_text_holds(tmp_path, cache, monkeypatch):
    odd = "A. Quill, “Eﬃcient port\u00ading of\x07patches\ud83d,” 2021."
    monkeypatch.setattr(references.reference_list, "read", lambda pdf: [types.SimpleNamespace(number=1, text=odd)])
    fake = FakeHallucinator("offline-run.json")
    run(tmp_path, cache, fake, monkeypatch, online=False)
    with pymupdf.open(fake.calls[0][0][-1]) as document:
        lines = document[0].get_text().splitlines()
    assert " ".join(lines[2].split()) == "[1] A. Quill, “Efficient porting of patches ,” 2021."


def test_local_run_reads_the_paper_itself_when_peercheck_finds_no_reference_list(tmp_path, cache, monkeypatch):
    fake = FakeHallucinator("offline-run.json")
    run(tmp_path, cache, fake, monkeypatch, online=False)
    assert fake.calls[0][0][-1] == str(tmp_path / "paper.pdf")


def test_online_false_disables_every_online_source_and_uses_the_local_dblp(tmp_path, cache, monkeypatch, indexes):
    fake = FakeHallucinator("offline-run.json")
    run(tmp_path, cache, fake, monkeypatch, online=False)
    command = fake.calls[0][0]
    assert sorted(fake.disabled()) == sorted([
        "CrossRef", "arXiv", "Semantic Scholar", "ACL Anthology", "Europe PMC", "PubMed", "DOI", "OpenAlex", "GovInfo",
        "PatentsView", "Standards", "Open Library", "SSRN"])
    assert command[command.index("--dblp-offline") + 1] == str(cache / "hallucinator" / "dblp.db")
    assert "--no-searxng" in command and "--url-match" not in command
    assert command[command.index("--config") + 1].endswith("hallucinator.toml")
    assert len(fake.calls) == 1
    assert indexes.nothing_asked()


def test_offline_run_hides_keys_and_proxies_of_the_user(tmp_path, cache, monkeypatch):
    monkeypatch.setenv("S2_API_KEY", "not-a-real-key")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:3128")
    fake = FakeHallucinator("offline-run.json")
    run(tmp_path, cache, fake, monkeypatch, online=False, online_titles=True)
    env = fake.calls[0][1]["env"]
    assert "S2_API_KEY" not in env and "HTTPS_PROXY" not in env
    assert env["HOME"] == str(tmp_path / "work" / "references")


def test_dblp_record_whose_title_and_author_stand_in_a_reference_confirms_it(tmp_path, cache, monkeypatch):
    # Hallucinator read a part of the venue into the title, therefore its own lookup found no record.
    dblp_database(cache, ("Do stable branches receive the fixes they need?",
                          ["Carla Marsh", "Dele Okafor", "Erik Lindqvist 0002"]))
    findings = run(tmp_path, cache, FakeHallucinator(report(QUESTION)), monkeypatch, online=False)
    assert not by_check(findings, "references.not-found")
    assert by_check(findings, "references.summary")[0].message.startswith("1 reference checked offline: 1 found")


def test_dblp_record_of_other_authors_does_not_confirm_a_reference(tmp_path, cache, monkeypatch):
    dblp_database(cache, ("Do stable branches receive the fixes they need?", ["Petra Zeller", "Hana Novak"]))
    findings = run(tmp_path, cache, FakeHallucinator(report(QUESTION)), monkeypatch, online=False)
    assert len(by_check(findings, "references.not-found")) == 1


def test_dblp_record_of_an_author_whose_family_name_is_a_word_after_the_title_does_not_confirm_a_reference(
        tmp_path, cache, monkeypatch):
    dblp_database(cache, ("Do stable branches receive the fixes they need?", ["Hoh Peter In", "Petra Zeller"]))
    findings = run(tmp_path, cache, FakeHallucinator(report(QUESTION)), monkeypatch, online=False)
    assert len(by_check(findings, "references.not-found")) == 1


@pytest.mark.parametrize(("cited", "found"), [(TITLE, 1), (f"{TITLE}: A field study", 0)])
def test_dblp_record_without_authors_confirms_only_a_reference_under_nearly_its_whole_title(tmp_path, cache,
                                                                                           monkeypatch, cited, found):
    dblp_database(cache, (TITLE, []))
    entry = {"title": cited, "raw_citation": ENTRY.replace(TITLE, cited)}
    findings = run(tmp_path, cache, FakeHallucinator(report(entry)), monkeypatch, online=False)
    assert by_check(findings, "references.summary")[0].message.startswith(
        f"1 reference checked offline: {found} found")


def test_dblp_record_of_the_cited_authors_confirms_beside_a_record_of_other_authors(tmp_path, cache, monkeypatch):
    dblp_database(cache, (TITLE, ["Petra Zeller", "Hana Novak"]), (TITLE, ["Ada Quill", "Ben Reed"]))
    findings = run(tmp_path, cache, FakeHallucinator(report({})), monkeypatch, online=False)
    assert by_check(findings, "references.summary")[0].message.startswith("1 reference checked offline: 1 found")


def test_dblp_record_of_other_authors_under_the_cited_title_is_reported_as_an_author_mismatch(tmp_path, cache,
                                                                                             monkeypatch):
    dblp_database(cache, (TITLE, ["Petra Zeller", "Hana Novak"]))
    findings = run(tmp_path, cache, FakeHallucinator(report({})), monkeypatch, online=False)
    [mismatch] = by_check(findings, "references.author-mismatch")
    assert mismatch.message.endswith("matches a title in DBLP whose authors differ: Petra Zeller, Hana Novak")


def test_mismatch_of_hallucinator_with_a_dblp_record_under_another_title_leaves_a_reference_not_found(
        tmp_path, cache, monkeypatch):
    # The DBLP lookup of Hallucinator accepts a title from a ratio of 0.90, and these two titles have 0.916.
    seventh = "A seventh made-up title on the porting of patches"
    dblp_database(cache, ("A fourteenth made-up title on the porting of patches", ["Petra Zeller", "Hana Novak"]))
    entry = {**OTHER_AUTHORS, "title": seventh, "raw_citation": ENTRY.replace(TITLE, seventh)}
    findings = run(tmp_path, cache, FakeHallucinator(report(entry)), monkeypatch, online=False)
    assert not by_check(findings, "references.author-mismatch")
    assert by_check(findings, "references.not-found")[0].message.endswith("was not found in DBLP")


def test_mismatch_of_hallucinator_names_the_authors_of_the_dblp_record_that_is_near_the_cited_title(
        tmp_path, cache, monkeypatch):
    dblp_database(cache, (f"{TITLE}s", ["Carla Marsh"]))
    findings = run(tmp_path, cache, FakeHallucinator(report(OTHER_AUTHORS)), monkeypatch, online=False)
    [mismatch] = by_check(findings, "references.author-mismatch")
    assert mismatch.message.endswith("matches a title in DBLP whose authors differ: Carla Marsh")


def test_mismatch_of_hallucinator_stays_for_a_dblp_record_under_the_cited_title_that_the_search_does_not_reach(
        tmp_path, cache, monkeypatch):
    monkeypatch.setattr(references, "CANDIDATES", 0)
    dblp_database(cache, (TITLE, ["Carla Marsh"]))
    entry = {**OTHER_AUTHORS, "paper_url": "https://dblp.org/rec/conf/made-up/1"}
    findings = run(tmp_path, cache, FakeHallucinator(report(entry)), monkeypatch, online=False)
    [mismatch] = by_check(findings, "references.author-mismatch")
    assert mismatch.message.endswith("matches a title in DBLP whose authors differ: Carla Marsh")


def test_dblp_record_that_hallucinator_accepts_for_one_of_three_cited_authors_is_reported_as_an_author_mismatch(
        tmp_path, cache, monkeypatch):
    dblp_database(cache, (TITLE, ["Ada Quill", "Petra Zeller", "Hana Novak"]))
    findings = run(tmp_path, cache, FakeHallucinator(report(ACCEPTED_FOR_ONE_AUTHOR)), monkeypatch)
    [mismatch] = by_check(findings, "references.author-mismatch")
    assert mismatch.message.endswith(
        "matches a title in DBLP whose authors differ: Ada Quill, Petra Zeller, Hana Novak")


def test_dblp_record_under_another_title_that_hallucinator_accepts_for_one_cited_author_leaves_a_reference_not_found(
        tmp_path, cache, monkeypatch):
    seventh = "A seventh made-up title on the porting of patches"
    dblp_database(cache, ("A fourteenth made-up title on the porting of patches",
                          ["Ada Quill", "Petra Zeller", "Hana Novak"]))
    entry = {**ACCEPTED_FOR_ONE_AUTHOR, "title": seventh,
             "raw_citation": ACCEPTED_FOR_ONE_AUTHOR["raw_citation"].replace(TITLE, seventh)}
    findings = run(tmp_path, cache, FakeHallucinator(report(entry)), monkeypatch, online=False)
    assert not by_check(findings, "references.author-mismatch")
    assert by_check(findings, "references.not-found")[0].message.endswith("was not found in DBLP")


def test_dblp_record_of_the_cited_authors_confirms_beside_the_record_of_other_authors_that_hallucinator_accepts(
        tmp_path, cache, monkeypatch):
    dblp_database(cache, (TITLE, ["Ada Quill", "Petra Zeller", "Hana Novak"]),
                  (TITLE, ["Ada Quill", "Tom Brennan", "Kenji Ito"]))
    findings = run(tmp_path, cache, FakeHallucinator(report(ACCEPTED_FOR_ONE_AUTHOR)), monkeypatch, online=False)
    assert by_check(findings, "references.summary")[0].message.startswith("1 reference checked offline: 1 found")


def test_mismatch_of_hallucinator_with_a_record_of_another_offline_database_stays(tmp_path, cache, monkeypatch):
    dblp_database(cache, ("A fourteenth made-up title on the porting of patches", ["Petra Zeller", "Hana Novak"]))
    other = {**OTHER_AUTHORS, "source": "ACL Anthology",
             "db_results": [{"db": "DBLP", "status": "no_match"}, {"db": "ACL Anthology", "status": "author_mismatch"}]}
    findings = run(tmp_path, cache, FakeHallucinator(report(other)), monkeypatch, online=False)
    [mismatch] = by_check(findings, "references.author-mismatch")
    assert mismatch.message.endswith("matches a title in ACL Anthology whose authors differ: Petra Zeller, Hana Novak")


def test_dblp_search_finds_a_title_whose_words_are_more_common_than_the_words_of_its_venue(tmp_path, cache,
                                                                                         monkeypatch):
    # Each word of the venue stands in one title of the database, and each word of the cited title in two.
    dblp_database(cache, ("Do stable branches receive the fixes they need?",
                          ["Carla Marsh", "Dele Okafor", "Erik Lindqvist"]),
                  ("They need the fixes that stable branches receive", ["Hana Novak"]),
                  ("Proc IEEE ACM 44th int conf softw eng", ["Petra Zeller"]))
    venue = "in Proc. IEEE/ACM 44th Int. Conf. Softw. Eng. (ICSE), Pittsburgh, PA, USA, May 2022, pp. 44–55."
    entry = {**QUESTION, "raw_citation": QUESTION["raw_citation"].split("in Proc.")[0] + venue}
    findings = run(tmp_path, cache, FakeHallucinator(report(entry)), monkeypatch, online=False)
    assert by_check(findings, "references.summary")[0].message.startswith("1 reference checked offline: 1 found")


def test_dblp_search_finds_a_title_that_hallucinator_read_from_another_part_of_the_entry(tmp_path, cache,
                                                                                         monkeypatch):
    # One other record holds two words of the title that Hallucinator read, and one a family name of the entry.
    dblp_database(cache, (TITLE, ["Ada Quill", "Ben Reed"]), ("The url of an arxiv preprint", ["Hana Novak"]),
                  ("The quill of a porcupine", ["Petra Zeller"]))
    address = {"title": "URL https://arxiv.org/abs/2101",
               "raw_citation": f"A. Quill and B. Reed. {TITLE}. arXiv preprint arXiv:2101.00001 (2021). "
                               "URL https://arxiv.org/abs/2101.00001"}
    findings = run(tmp_path, cache, FakeHallucinator(report(address)), monkeypatch, online=False)
    assert by_check(findings, "references.summary")[0].message.startswith("1 reference checked offline: 1 found")


def test_dblp_search_counts_the_titles_of_each_word_once_for_the_references_of_a_paper(tmp_path, cache, monkeypatch):
    dblp_database(cache, (TITLE, ["Ada Quill", "Ben Reed"]))
    asked = []
    connect = sqlite3.connect

    def traced(*args, **kwargs):
        records = connect(*args, **kwargs)
        records.set_trace_callback(asked.append)
        return records

    monkeypatch.setattr(references.sqlite3, "connect", traced)
    run(tmp_path, cache, FakeHallucinator(report({}, {})), monkeypatch, online=False)
    counted = [statement for statement in asked if "temp.vocabulary where term = 'porting'" in statement]
    assert len(counted) == 1


@pytest.mark.parametrize("answer", [
    {"status": "inconclusive", "failed_dbs": ["DBLP"], "db_results": [{"db": "DBLP", "status": "error"}]},
    {"db_results": []}])
def test_reference_that_the_local_dblp_did_not_answer_gets_a_note_and_no_warning(tmp_path, cache, monkeypatch, answer):
    findings = run(tmp_path, cache, FakeHallucinator(report(answer)), monkeypatch, online=False)
    assert not by_check(findings, "references.not-found")
    assert by_check(findings, "references.unchecked")[0].message == (
        "Reference [1] was not looked up, since the lookup failed at DBLP. A later run repeats the lookup")


def test_reference_that_the_local_dblp_did_not_answer_is_found_once_an_online_source_confirms_it(tmp_path, cache,
                                                                                                monkeypatch, indexes):
    indexes.openalex[TITLE] = [Work(TITLE, ("Ada Quill", "Ben Reed"))]
    findings = run(tmp_path, cache, FakeHallucinator(report({"db_results": []})), monkeypatch)
    assert [finding.check for finding in findings] == ["references.summary"]


def test_dblp_title_that_is_a_part_of_the_cited_title_does_not_confirm_a_reference(tmp_path, cache, monkeypatch):
    dblp_database(cache, ("Stable branches receive the fixes", ["Carla Marsh", "Dele Okafor"]))
    findings = run(tmp_path, cache, FakeHallucinator(report(QUESTION)), monkeypatch, online=False)
    assert len(by_check(findings, "references.not-found")) == 1


def test_dblp_title_of_fewer_than_16_letters_does_not_confirm_a_reference(tmp_path, cache, monkeypatch):
    dblp_database(cache, ("Deep patch search", ["Ada Quill"]))
    findings = run(tmp_path, cache, FakeHallucinator(report(SHORT)), monkeypatch, online=False)
    assert by_check(findings, "references.summary")[0].message.startswith("1 reference checked offline: 0 found")


def test_rare_word_cut_at_a_line_end_still_finds_the_dblp_title(tmp_path, cache, monkeypatch):
    # Every other word of the title stands in too many titles to search for.
    monkeypatch.setattr(references, "COMMON_TITLE_WORD", 2)
    dblp_database(cache, ("Backporting considered harmful", ["Ada Quill"]),
                  ("Mocking considered harmful", ["Hana Novak"]), ("Refactoring considered harmful", ["Petra Zeller"]))
    cut = {"title": "Back- porting considered harmful",
           "raw_citation": "A. Quill, “Back- porting considered harmful,” in Proc. Int. Conf. Softw. Eng., 2021."}
    findings = run(tmp_path, cache, FakeHallucinator(report(cut)), monkeypatch, online=False)
    assert by_check(findings, "references.summary")[0].message.startswith("1 reference checked offline: 1 found")


def test_record_that_names_half_of_the_cited_authors_confirms_a_reference():
    ref = parsed(status="mismatch", ref_authors=["A. Quill", "B. Reed", "C. Marsh", "D. Okafor"],
                 found_authors=["Ada Quill", "Ben Reed", "Hana Novak"],
                 db_results=[{"db": "DBLP", "status": "author_mismatch"}])
    assert ref.status == "verified"


def test_record_that_names_fewer_than_half_of_the_cited_authors_stays_a_mismatch():
    ref = parsed(status="mismatch", ref_authors=["A. Quill", "B. Reed", "C. Marsh"],
                 found_authors=["Ada Quill", "Hana Novak", "Petra Zeller"],
                 db_results=[{"db": "DBLP", "status": "author_mismatch"}])
    assert ref.status == "mismatch"


def test_record_that_hallucinator_accepts_for_fewer_than_half_of_the_cited_authors_is_a_mismatch():
    # Hallucinator 0.2.4 accepts a record once it names one cited author.
    ref = parsed(**ACCEPTED_FOR_ONE_AUTHOR)
    assert (ref.status, ref.record_source, ref.record_authors, ref.record_url) == (
        "mismatch", "DBLP", ("Ada Quill", "Petra Zeller", "Hana Novak"), "https://dblp.org/rec/conf/made-up/1")


@pytest.mark.parametrize("found", [["Ada Quill", "Ben Reed", "Hana Novak"], [], ["张伟"], ["The Made-up Team"]])
def test_record_that_hallucinator_accepts_stays_accepted_unless_it_names_other_authors(found):
    ref = parsed(status="verified", source="DBLP", found_authors=found, db_results=[{"db": "DBLP", "status": "match"}])
    assert (ref.status, ref.record_source, ref.record_authors) == ("verified", "", ())


def test_record_without_authors_confirms_a_reference():
    ref = parsed(status="mismatch", found_authors=[], db_results=[{"db": "DOI", "status": "author_mismatch"}])
    assert ref.status == "verified"


def test_cited_name_with_the_family_name_first_is_compared_by_that_name():
    ref = parsed(status="mismatch", ref_authors=["Wilson, E. B."], found_authors=["Edwin Wilson"],
                 db_results=[{"db": "CrossRef", "status": "author_mismatch"}])
    assert ref.status == "verified"


def test_cited_names_with_the_initial_last_do_not_confirm_a_record_of_other_authors():
    ref = parsed(status="mismatch", ref_authors=["Brennan T", "Ito KM"], found_authors=["Petra Zeller", "Hana Novak"],
                 db_results=[{"db": "DBLP", "status": "author_mismatch"}])
    assert ref.status == "mismatch"


def test_record_with_a_cut_author_list_that_names_only_cited_authors_confirms_a_reference():
    cited = ["A. Quill", "B. Reed", "C. Marsh", "D. Okafor", "E. Lindqvist"]
    ref = parsed(status="mismatch", ref_authors=cited, found_authors=["Ada Quill"], source="CrossRef",
                 db_results=[{"db": "CrossRef", "status": "author_mismatch"}])
    assert ref.status == "verified"


def test_record_that_hallucinator_set_aside_for_its_authors_confirms_a_reference_when_it_names_cited_authors():
    # Hallucinator reports no mismatch for a title of fewer than six words and gives the authors with the result.
    ref = parsed(ref_authors=["A. Quill", "B. Reed", "C. Marsh"],
                 db_results=[{"db": "CrossRef", "status": "author_mismatch", "authors": ["Ada Quill"]}])
    assert (ref.status, ref.answered) == ("verified", ("CrossRef",))


@pytest.mark.parametrize("authors", [["Petra Zeller", "Hana Novak"], [], ["张伟"]])
def test_record_that_hallucinator_set_aside_leaves_a_reference_not_found_unless_it_names_cited_authors(authors):
    ref = parsed(db_results=[{"db": "CrossRef", "status": "author_mismatch", "authors": authors}])
    assert (ref.status, ref.answered) == ("not_found", ("CrossRef",))


def test_letter_with_a_stroke_reads_as_its_plain_letter_in_a_name():
    ref = parsed(status="mismatch", ref_authors=["J. Łukasiewicz"], found_authors=["Jan Lukasiewicz"],
                 db_results=[{"db": "CrossRef", "status": "author_mismatch"}])
    assert ref.status == "verified"


def test_written_out_umlaut_reads_as_its_letter_in_a_name():
    ref = parsed(status="mismatch", ref_authors=["E. Mueller"], found_authors=["Erna Müller"],
                 db_results=[{"db": "DBLP", "status": "author_mismatch"}])
    assert ref.status == "verified"


def test_doi_that_hallucinator_calls_invalid_leaves_a_record_of_the_cited_authors_as_found():
    # Hallucinator 0.2.4 calls a DOI invalid also when its lookup failed, as for seven real DOIs of one test run.
    ref = parsed(status="mismatch", found_authors=["Ada Quill", "Ben Reed"], source="CrossRef",
                 doi_info={"doi": DOI, "valid": False, "title": None},
                 db_results=[{"db": "DOI", "status": "no_match"}, {"db": "CrossRef", "status": "match"}])
    assert (ref.status, ref.dois) == ("verified", (DOI,))


@pytest.mark.parametrize("entry", [
    "Anonymous. Artifact of a made-up tool. https://doi.org/10.5555/zenodo.0000000",
    "Anonymous Author(s), “A made-up title on the porting of patches,” in Proc. Int. Conf. Softw. Eng., 2021.",
    "[Details omitted for double-blind reviewing], in Proc. Int. Conf. Softw. Eng., 2021.",
    "A made-up title on the porting of patches. Anonymized for review. In Proc. Int. Conf. Softw. Eng., 2021.",
    "Anon. 2021. A made-up title on the porting of patches. In Proc. Int. Conf. Softw. Eng.",
    "Author(s) anonymized. A made-up title on the porting of patches. In Proc. Int. Conf. Softw. Eng., 2021.",
    "Removed for double blind review. A made-up title on the porting of patches. In Proc. Int. Conf. Softw. Eng.",
    "Omitted for the double-blind review. A made-up title on the porting of patches. In Proc. Int. Conf. Softw. Eng.",
    "Details omitted due to double-blind reviewing. A made-up title on the porting of patches, 2021.",
    "Suppressed for anonymity. A made-up title on the porting of patches. In Proc. Int. Conf. Softw. Eng., 2021.",
    "Withheld to preserve anonymity. A made-up title on the porting of patches. In Proc. Int. Conf. Softw. Eng.",
    "Hidden for submission. A made-up title on the porting of patches. In Proc. Int. Conf. Softw. Eng., 2021.",
    "Redacted for anonymity. A made-up title on the porting of patches. In Proc. Int. Conf. Softw. Eng., 2021.",
    "XXX and YYY, “A made-up title on the porting of patches,” in Proc. Int. Conf. Softw. Eng., 2021 (anonymized).",
    "Blinded, “A made-up title on the porting of patches,” in Proc. Int. Conf. Softw. Eng., 2021.",
    "[Blinded for review], “A made-up title on the porting of patches,” in Proc. Int. Conf. Softw. Eng., 2021.",
    "Self-reference hidden. A made-up title on the porting of patches. In Proc. Int. Conf. Softw. Eng., 2021.",
    "Self-citation. A made-up title on the porting of patches. In Proc. Int. Conf. Softw. Eng., 2021.",
    "A replication package of the authors (link removed to keep anonymity), 2021, pp. 1–2.",
    "A made-up title on the porting of patches. Omitted to ensure anonymity. In Proc. Int. Conf. Softw. Eng., 2021.",
    "A made-up title on the porting of patches. Removed to maintain anonymity. In Proc. Int. Conf. Softw. Eng.",
    "A made-up title on the porting of patches. Withheld because of the blind review. In Proc. Int. Conf. Softw. Eng.",
    "A made-up title on the porting of patches. Omitted for blind reviewing. In Proc. Int. Conf. Softw. Eng., 2021.",
    "A. Quill, [redacted], in Proc. Int. Conf. Softw. Eng., 2021.",
    "A. Quill, (blinded), in Proc. Int. Conf. Softw. Eng., 2021.",
    "Own work (authors redacted). A made-up title on the porting of patches. In Proc. Int. Conf. Softw. Eng., 2021.",
    "Author names removed. A made-up title on the porting of patches. In Proc. Int. Conf. Softw. Eng., 2021.",
    "Author details omitted. A made-up title on the porting of patches. In Proc. Int. Conf. Softw. Eng., 2021.",
    "Authors’ own work, anonymized. A made-up title on the porting of patches. In Proc. Int. Conf. Softw. Eng., 2021.",
    "Names withheld, “A made-up title on the porting of patches,” in Proc. Int. Conf. Softw. Eng., 2021.",
    "[Anonymous], “A made-up title on the porting of patches,” in Proc. ICSE, 2021 [anonymous submission].",
    "XXX and YYY, “A made-up title on the porting of patches,” in Proc. Int. Conf. Softw. Eng., 2021. Names hidden.",
    "Our earlier work, “A made-up title on the porting of patches,” in Proc. ICSE, 2021, citation anonymized.",
    "Our earlier work. A made-up title on the porting of patches. Citation suppressed. In Proc. Int. Conf. Softw. Eng.",
    "Under double-blind review, “A made-up title on the porting of patches,” in Proc. Int. Conf. Softw. Eng., 2021.",
    "Under blind review. A made-up title on the porting of patches. In Proc. Int. Conf. Softw. Eng., 2021."])
def test_entry_by_anonymous_or_with_its_details_left_out_hides_a_work_for_the_review(entry):
    assert references._is_hidden(parsed(raw_citation=entry))


@pytest.mark.parametrize("verb", ["omitted", "anonymized", "anonymised", "blinded", "removed", "hidden", "redacted",
                                  "withheld", "suppressed"])
def test_entry_whose_authors_are_left_out_in_any_of_the_words_for_it_hides_a_work_for_the_review(verb):
    entry = f"Authors {verb}, “{TITLE},” in Proc. Int. Conf. Softw. Eng., 2021."
    assert references._is_hidden(parsed(raw_citation=entry))


@pytest.mark.parametrize("entry", [
    "A. Quill, “Anonymous functions in practice,” in Proc. Int. Conf. Softw. Eng., 2021.",
    "A. Quill, “Double-blinded review at venues of software engineering,” in Proc. Int. Conf. Softw. Eng., 2021.",
    "A. Quill, “Anonymized traces for the review of patches,” in Proc. Int. Conf. Softw. Eng., 2021.",
    "A. Quill, “Patches (hidden Markov models) in practice,” in Proc. Int. Conf. Softw. Eng., 2021.",
    "A. Quill, “Hidden technical debt in made-up build systems,” in Proc. Int. Conf. Softw. Eng., 2021.",
    "Ada Quill. 2021. Hidden technical debt in made-up build systems. In Proceedings of the Made-up Meeting. 1–12.",
    "A. Quill, “Anonymized trace data for the reproducible study of patches,” in Proc. Int. Conf. Softw. Eng., 2021.",
    "Ada Quill. 2021. Anonymized trace data for the reproducible study of patches. In Proc. Made-up Meeting. 1–12.",
    "A. Quill, “Patches that the maintainers withheld,” in Proc. Int. Conf. Softw. Eng., 2021.",
    "A. Quill, “A made-up trial of the review of patches (double-blinded),” in Proc. Int. Conf. Softw. Eng., 2021.",
    "A. Quill, “Reviews of patches with the names of the authors hidden,” Made-up Softw. Eng., vol. 26, 2021.",
    "A. Quill and B. Reed, “Patches under double-blind review,” in Proc. Int. Conf. Softw. Eng., 2021.",
    "A. Quill, “The made-up kernel documentation,” 2021, the page was later removed and its address leads elsewhere.",
    "Anon Quill and Ben Reed. 2021. A made-up title on the porting of patches. In Proceedings of the Made-up Meeting."])
def test_entry_that_names_a_hidden_thing_in_its_title_hides_no_work(entry):
    assert not references._is_hidden(parsed(raw_citation=entry))


@pytest.mark.parametrize("authors", ["authors", "au- thors"])
def test_title_that_ends_a_sentence_with_a_word_for_left_out_hides_no_work(authors):
    title = "How the review of patches changes once the names of the authors are removed"
    entry = (f"Ada Quill and Ben Reed. 2021. {title.replace('authors', authors)}. In Proceedings of the Made-up "
             "Meeting. 101–112.")
    assert not references._is_hidden(parsed(title=title, raw_citation=entry))


def test_note_on_what_the_authors_left_out_hides_an_entry_without_a_title():
    assert references._is_hidden(parsed(title="", raw_citation="XXX and YYY, 2021. Names hidden."))


@pytest.mark.parametrize("authors", ["Anon. 2021", "Own work (authors redacted)", "Author names removed"])
def test_title_of_a_hidden_entry_goes_to_no_source(tmp_path, cache, monkeypatch, indexes, authors):
    hidden = {"raw_citation": f"{authors}. {TITLE}. In Proc. Int. Conf. Softw. Eng., doi: {DOI}.", "ref_authors": []}
    fake = FakeHallucinator(report(hidden))
    findings = run(tmp_path, cache, fake, monkeypatch)
    assert len(fake.calls) == 1 and indexes.nothing_asked()
    assert by_check(findings, "references.unchecked")[0].message == (
        "Reference [1] was not looked up. Such an entry hides a work for the review, names a web page, or bears no "
        "title of four words or more")


def test_hidden_entry_that_the_local_database_holds_counts_as_found(tmp_path, cache, monkeypatch, indexes):
    hidden = {"raw_citation": f"Anonymous. {TITLE}. In Proc. Int. Conf. Softw. Eng., 2021.", "status": "verified",
              "db_results": [{"db": "DBLP", "status": "match"}]}
    findings = run(tmp_path, cache, FakeHallucinator(report(hidden)), monkeypatch)
    assert [finding.check for finding in findings] == ["references.summary"]
    assert findings[0].message.endswith("1 found, 0 not found, 0 with other authors or identifiers, 0 not looked up")
    assert indexes.nothing_asked()


def test_answer_of_the_online_run_for_a_title_that_opens_with_anonymous_is_read(tmp_path, cache, monkeypatch):
    title = "Anonymous functions in the practice of patches"
    entry = {"title": title, "ref_authors": [], "raw_citation": ENTRY.replace(TITLE, title)}
    online = report({"title": title, "ref_authors": [], "raw_citation": title,
                     "db_results": [{"db": "CrossRef", "status": "no_match"}]})
    findings = run(tmp_path, cache, FakeHallucinator(report(entry), online), monkeypatch)
    assert by_check(findings, "references.not-found")[0].message.endswith(
        "was not found in DBLP, CrossRef, DataCite, OpenAlex")


@pytest.mark.parametrize(("entry", "recent"), [
    ("A. Quill, “A made-up title,” in Proc. Int. Conf. Softw. Eng., {this}, pp. 1–12.", True),
    ("A. Quill, “A made-up title,” in Proc. Int. Conf. Softw. Eng., {last}.", True),
    ("A. Quill, “A made-up title,” in Proc. Int. Conf. Softw. Eng.", True),
    ("A. Quill, “A made-up title,” in Proc. Int. Conf. Softw. Eng., {old}.", False),
    ("A. Quill, “A made-up title,” {old}, doi: 10.5555/tse.{this}.1234567, arXiv:{this}.01234.", False)])
def test_newest_year_of_an_entry_says_whether_it_is_recent(entry, recent):
    this = datetime.date.today().year
    ref = parsed(raw_citation=entry.format(this=this, last=this - 1, old=this - 2))
    assert references._is_recent(ref) is recent


@pytest.mark.parametrize("venue", [
    "in Proceedings of the Made-up Meeting, 2021", "in Proc. Made-up Meeting, 2021", "in Made-up Conference, 2021",
    "in Int. Conf. Made-up Patches, 2021", "in Made-up Symposium, 2021", "in Made-up Symp., 2021",
    "in Made-up Workshop, 2021", "Made-up Journal, 2021", "Made-up Transactions, 2021", "Made-up Trans., 2021",
    "Made-up Letters, 2021", "Made-up Magazine, 2021", "arXiv:2101.00001", "CoRR, 2021", "preprint, 2021",
    "Made-up Review, vol. 3, 2021", "Made-up Review, 2021, pp. 3", "Made-up Review, 2021, Article 12",
    "Made-up Review, 2021, doi: 10.5555/1", "Made-up Review, 2021, 101–112", "Made-up Review, 2021, 101--112",
    "Made-up Review 3, 2021, 12:1–12:25", "in Proc. 3rd Edition of the Made-up Meeting, 2021"])
def test_entry_with_a_venue_a_volume_pages_or_an_identifier_names_an_article(venue):
    assert references._is_article(parsed(raw_citation=f"T. Iso and A. Quill, “{TITLE},” {venue}."))


@pytest.mark.parametrize("entry", [
    f"A. Quill and B. Reed, “{TITLE},” in ICSE, 2021.", f"A. Quill and B. Reed, “{TITLE},” in NeurIPS, 2021.",
    f"A. Quill and B. Reed, “{TITLE},” in ICSE’21, pp. 1–12.", f"A. Quill and B. Reed, “{TITLE},” in ESEC/FSE 2021.",
    f"Ada Quill and Ben Reed. 2021. {TITLE}. In ICSE. 2021.", f"Ada Quill and Ben Reed. 2021. {TITLE}. In ICSE ’21.",
    f"Quill, A., Reed, B.: {TITLE}. In: ASE (2021)", f"Ada Quill and Ben Reed. {TITLE}. In ICSE"])
def test_entry_that_goes_on_after_its_title_with_the_short_name_of_a_venue_names_an_article(entry):
    assert references._is_article(parsed(raw_citation=entry))


@pytest.mark.parametrize("venue", [
    "Made-up Softw. Eng. 26(3), 1-34 (2021)", "Made-up Review 26, 3 (2021), 101-112", "Made-up Softw Eng 26(3):1-34",
    "Made-up Review 26 (2021) 101-112", "Made-up Review 26, 101-112, 2021"])
def test_hyphen_between_two_numbers_after_a_volume_an_issue_or_a_year_marks_pages(venue):
    assert references._is_article(parsed(raw_citation=f"A. Quill and B. Reed, “{TITLE},” {venue}."))


@pytest.mark.parametrize("rest", [
    "Made-up Review, accessed 2024-03-01", "Made-up Review, accessed: 2024-03-01", "Made-up Review, 2024-03",
    "Made-up Review, 2019-2023", "Made-up Review, 1999–2001", "Made-up Review, 1999--2001",
    "Meadow Press, ISBN 978-3-16-148410-0", "Meadow Press, ISBN: 1-4020-7653-8", "Made-up Review, ISSN: 1573-7616",
    "Made-up Review, ISSN 1573-7616", "Made-up Advisory, CVE-2022-2730", "Made-up Publication 800-162",
    "Made-up Meeting, Springfield, March 21-24, 2022", "Made-up Meeting, Springfield, 3-5 June 2021",
    "Made-up Meeting, Springfield, Sept. 3-5, 2021", "Made-up Survey, 1,993-2,100 developers",
    "Made-up Hub dataset, release range: 14.1.1–15.0.0", "Made-up registry, snapshot for 2026-09-24–2026-09-30",
    "Made-up Review, sections 3.1–3.4", "2021. Implemented in OCaml", "2021. In preparation"])
def test_number_range_that_is_no_range_of_pages_and_a_word_in_capitals_after_other_words_name_no_article(rest):
    assert not references._is_article(parsed(raw_citation=f"A. Quill and B. Reed, “{TITLE},” {rest}."))


def test_word_in_capitals_after_in_inside_a_title_is_no_short_name_of_a_venue():
    title = "An empirical made-up study of bugs in GCC"
    assert not references._is_article(parsed(title=title, raw_citation=f"A. Quill, “{title},” 2021."))


@pytest.mark.parametrize("entry", [
    {"raw_citation": f"A. Quill, “{TITLE},” Made-up Review, 2021."},
    {"title": "Deep patch search",
     "raw_citation": "A. Quill, “Deep patch search,” in Proc. Int. Conf. Softw. Eng., 2021, pp. 101–112."},
    {"title": "The Art of Made-up Programming",
     "raw_citation": "D. Kneath, The Art of Made-up Programming, vol. 1, 3rd ed. Springfield: Meadow Press, 1997."},
    {"title": "Maintaining Stable Releases: A Field Guide",
     "raw_citation": "P. Zeller, Maintaining Stable Releases: A Field Guide, 2nd ed. Springfield: Meadow Press, 2019, "
                     "ch. 3, pp. 45–67."},
    {"title": "The made-up kernel documentation",
     "raw_citation": "Made-up Kernel Organization, “The made-up kernel documentation,” 2019–2023."},
    {"title": "Software and systems engineering — Software testing — Part 1",
     "raw_citation": "Software and systems engineering — Software testing — Part 1, ISO/IEC/IEEE Std. 29119–1, 2013."},
    {"title": "A made-up doctoral thesis on patches",
     "raw_citation": "A. Quill, “A made-up doctoral thesis on patches,” Ph.D. dissertation, Dept. Comput. Sci., "
                     "Meadow Univ., Springfield, 2019, 1–210."},
    {"raw_citation": f"A. Quill, “{TITLE},” Meadow Univ., Springfield, Tech. Rep. 12, 2021, pp. 1–20."},
    {"raw_citation": f"A. Quill, “{TITLE},” RFC 9999, 2021, pp. 1–20."},
    {"raw_citation": f"A. Quill, “{TITLE},” Zenodo, 2021, doi: 10.5555/1."}])
def test_entry_of_a_book_a_web_page_a_standard_a_thesis_a_report_or_an_upload_names_no_article(entry):
    assert not references._is_article(parsed(**entry))


@pytest.mark.parametrize("mark", [
    "3rd ed.", "second edition", "Revised Ed.", "new edition", "ch. 3", "chap. 3", "Chapter 3", "IEEE Std 1012-2016",
    "Standard 1012", "ISO 26262", "RFC 9999", "Master’s thesis", "Ph.D. dissertation", "Tech. Rep. 12",
    "Technical Report 12", "Zenodo", "figshare", "Dryad", "Harvard Dataverse", "Software Heritage"])
def test_each_mark_of_a_work_that_the_databases_often_lack_makes_an_entry_with_pages_no_article(mark):
    assert not references._is_article(parsed(raw_citation=f"{ENTRY[:-1]}, {mark}."))


@pytest.mark.parametrize("venue", [
    "presented at the Made-up Developer Conference, Springfield, 2021, Paper 12",
    "keynote at the Made-up Kernel Workshop, 2021", "invited talk, Made-up Symposium, 2021",
    "talk at the Made-up Symposium, 2021", "Made-up Engineering Blog, vol. 3, 2021, pp. 1–3",
    "in ICLR Blog Track, 2022"])
def test_entry_of_a_talk_or_a_blog_post_names_no_article(venue):
    assert not references._is_article(parsed(raw_citation=f"A. Quill, “{TITLE},” {venue}."))


@pytest.mark.parametrize("title", [
    "A thesis on the standard 2 of patches", "Lessons presented at a keynote and an invited talk on a blog"])
def test_word_such_as_thesis_in_the_title_of_an_article_leaves_it_an_article(title):
    assert references._is_article(parsed(title=title, raw_citation=ENTRY.replace(TITLE, title)))


def test_word_such_as_thesis_in_a_title_that_a_line_end_cut_in_the_entry_leaves_an_article():
    title = "A thesis on the backporting of patches"
    cut = ENTRY.replace(TITLE, "A thesis on the back- porting of patches")
    assert references._is_article(parsed(title=title, raw_citation=cut))


def test_short_name_of_a_venue_after_a_title_that_a_line_end_cut_in_the_entry_names_an_article():
    title = "A made-up title on the backporting of patches"
    cut = "A. Quill and B. Reed, “A made-up title on the back- porting of patches,” in ICSE, 2021."
    assert references._is_article(parsed(title=title, raw_citation=cut))


def test_lookup_that_failed_at_a_side_source_counts_as_not_found():
    ref = parsed(status="inconclusive", failed_dbs=["Open Library"],
                 db_results=[{"db": "CrossRef", "status": "no_match"}, {"db": "Open Library", "status": "error"}])
    assert (ref.status, ref.answered, ref.failed) == ("not_found", ("CrossRef",), ())
    assert references._outcome(ref) == "not found"


def test_lookup_that_failed_at_crossref_leaves_a_reference_not_looked_up():
    ref = parsed(status="inconclusive", failed_dbs=["CrossRef"], db_results=[{"db": "CrossRef", "status": "timeout"}])
    assert (ref.status, ref.answered, ref.failed) == ("not_found", (), ("CrossRef",))
    assert references._outcome(ref) == "not looked up"


def test_titles_off_runs_hallucinator_once_and_without_an_online_source(tmp_path, cache, monkeypatch):
    fake = FakeHallucinator("online-run.json")
    run(tmp_path, cache, fake, monkeypatch, online_titles=False)
    assert set(references.ONLINE_SOURCES) - set(fake.disabled(0)) == {"DBLP"}
    assert len(fake.calls) == 1


def test_titles_off_asks_datacite_for_the_arxiv_ids_and_sends_no_title(tmp_path, cache, monkeypatch, indexes):
    run(tmp_path, cache, FakeHallucinator("online-run.json"), monkeypatch, online_titles=False)
    assert indexes.asked == {"dois": [["10.48550/arxiv.1207.7214", "10.48550/arxiv.1706.03762"]], "crossref_dois": [],
                             "agencies": [], "datacite": [], "openalex": [], "openreview": []}


def test_datacite_gets_an_old_arxiv_id_without_its_subject_class_as_arxiv_registers_it(tmp_path, cache, monkeypatch,
                                                                                       indexes):
    old = {"raw_citation": f"A. Quill and B. Reed, “{TITLE},” 2006, arXiv:cs.SE/0601001."}
    indexes.dois["10.48550/arxiv.cs/0601001"] = Work(TITLE, ("Ada Quill", "Ben Reed"))
    findings = run(tmp_path, cache, FakeHallucinator(report(old)), monkeypatch, online_titles=False)
    assert indexes.asked["dois"] == [["10.48550/arxiv.cs/0601001"]]
    assert by_check(findings, "references.summary")[0].message.endswith(
        "1 found, 0 not found, 0 with other authors or identifiers, 0 not looked up")


def test_crossref_gets_the_dois_that_datacite_does_not_hold_and_confirms_a_reference(tmp_path, cache, monkeypatch,
                                                                                     indexes):
    indexes.dois["10.5555/zenodo.1"] = Work("A made-up data set on patches", ("Ada Quill",))
    indexes.crossref_dois[DOI.lower()] = Work(TITLE.upper(), ("Ada Quill", "Ben Reed"))
    data = {"title": "A made-up data set on patches",
            "raw_citation": "A. Quill, A made-up data set on patches. Zenodo, 2021, doi: 10.5555/zenodo.1."}
    findings = run(tmp_path, cache, FakeHallucinator(report(WITH_DOI, data)), monkeypatch, online_titles=False)
    assert indexes.asked["dois"] == [["10.5555/3377811.3380362", "10.5555/zenodo.1"]]
    assert indexes.asked["crossref_dois"] == [["10.5555/3377811.3380362"]]
    assert indexes.asked["agencies"] == []
    assert by_check(findings, "references.summary")[0].message.startswith(
        "2 references checked with DOI and arXiv ID lookups: 2 found")


def test_crossref_that_does_not_answer_leaves_the_records_of_datacite(tmp_path, cache, monkeypatch, indexes):
    indexes.down = {"crossref_dois"}
    indexes.dois[DOI.lower()] = Work(TITLE, ("Ada Quill",))
    other = {"title": "A second made-up title on the porting of patches",
             "raw_citation": "C. Marsh, “A second made-up title on the porting of patches,” in Proc. Int. Conf. Softw. "
                             "Eng., 2021, doi: 10.5555/1."}
    findings = run(tmp_path, cache, FakeHallucinator(report(WITH_DOI, other)), monkeypatch, online_titles=False)
    [missing] = by_check(findings, "references.not-found")
    assert missing.message.startswith("Reference [2] ") and missing.message.endswith("was not found in DBLP")


def test_doi_of_another_registration_agency_gets_a_note_and_no_warning(tmp_path, cache, monkeypatch, indexes):
    indexes.agencies[DOI.lower()] = "ISTIC"
    findings = run(tmp_path, cache, FakeHallucinator(report(WITH_DOI)), monkeypatch, online_titles=False)
    assert indexes.asked["agencies"] == [[DOI.lower()]]
    assert not by_check(findings, "references.not-found")
    assert by_check(findings, "references.unconfirmed")[0].message.startswith("Reference [1] was not found, as is")
    assert by_check(findings, "references.summary")[0].message.endswith(
        "0 found, 1 not found, 0 with other authors or identifiers, 0 not looked up")


def test_reference_with_a_doi_of_another_registration_agency_goes_on_to_the_title_lookups(tmp_path, cache, monkeypatch,
                                                                                         indexes):
    indexes.agencies[DOI.lower()] = "JaLC"
    indexes.openalex[TITLE] = [Work(TITLE, ("Ada Quill", "Ben Reed"))]
    findings = run(tmp_path, cache, FakeHallucinator(report(WITH_DOI)), monkeypatch)
    assert indexes.asked["openalex"] == [TITLE]
    assert by_check(findings, "references.summary")[0].message.startswith(
        "1 reference checked with online title lookups: 1 found")


@pytest.mark.parametrize("record", [
    Work("机器学习软件工程的虚构标题", ("张伟", "陈丽")),
    Work("Заголовок статьи о переносе исправлений", ("Иван Иванов",)),
    Work("", ("Petra Zeller",))])
def test_record_of_a_doi_without_a_title_or_under_a_title_in_another_script_gets_a_note_and_no_warning(
        tmp_path, cache, monkeypatch, indexes, record):
    indexes.crossref_dois[DOI.lower()] = record
    findings = run(tmp_path, cache, FakeHallucinator(report(WITH_DOI)), monkeypatch, online_titles=False)
    assert not by_check(findings, "references.not-found")
    assert len(by_check(findings, "references.unconfirmed")) == 1


def test_reference_whose_doi_crossref_holds_is_not_looked_up_while_crossref_does_not_answer(tmp_path, cache,
                                                                                           monkeypatch, indexes):
    indexes.down = {"crossref_dois"}
    indexes.dois["10.5555/zenodo.1"] = Work("A made-up data set on patches", ("Ada Quill",))
    indexes.agencies[DOI.lower()] = "Crossref"
    data = {"title": "A made-up data set on patches",
            "raw_citation": "A. Quill, A made-up data set on patches. Zenodo, 2021, doi: 10.5555/zenodo.1."}
    findings = run(tmp_path, cache, FakeHallucinator(report(WITH_DOI, data)), monkeypatch, online_titles=False)
    assert indexes.asked["agencies"] == [[DOI.lower()]]
    assert not by_check(findings, "references.not-found")
    assert by_check(findings, "references.unchecked")[0].message == (
        "Reference [1] was not looked up, since the lookup failed at CrossRef. A later run repeats the lookup")
    assert by_check(findings, "references.summary")[0].message.endswith(
        "1 found, 0 not found, 0 with other authors or identifiers, 1 not looked up")


def test_reference_with_a_doi_is_not_looked_up_while_no_registry_answers(tmp_path, cache, monkeypatch, indexes):
    indexes.down = {"dois", "crossref_dois", "agencies"}
    findings = run(tmp_path, cache, FakeHallucinator(report(WITH_DOI)), monkeypatch, online_titles=False)
    assert not by_check(findings, "references.not-found")
    assert by_check(findings, "references.unchecked")[0].message.startswith(
        "Reference [1] was not looked up, since the lookup failed at DataCite, CrossRef, doi.org.")


def test_note_on_failed_lookups_names_for_each_reference_the_sources_that_failed_for_it(tmp_path, cache, monkeypatch,
                                                                                        indexes):
    indexes.down = {"crossref_dois"}
    indexes.agencies[DOI.lower()] = "Crossref"
    local = report(WITH_DOI, {"db_results": []}, WITH_DOI)
    findings = run(tmp_path, cache, FakeHallucinator(local), monkeypatch, online_titles=False)
    notes = by_check(findings, "references.unchecked")
    assert [note.message.removesuffix(". A later run repeats the lookup") for note in notes] == [
        "References [1] and [3] were not looked up, since the lookup failed at CrossRef",
        "Reference [2] was not looked up, since the lookup failed at DBLP"]
    assert [note.evidence for note in notes] == [f"[1] {TITLE}; [3] {TITLE}", f"[2] {TITLE}"]


def test_data_set_with_a_doi_of_datacite_is_not_looked_up_while_datacite_does_not_answer(tmp_path, cache, monkeypatch,
                                                                                        indexes):
    indexes.down = {"dois", "datacite"}
    indexes.agencies["10.5555/zenodo.1"] = "DataCite"
    data = {"title": "A made-up data set on patches of stable branches",
            "raw_citation": "A. Quill, “A made-up data set on patches of stable branches,” in Proc. Int. Conf. Softw. "
                            "Eng., 2021, doi: 10.5555/zenodo.1."}
    findings = run(tmp_path, cache, FakeHallucinator(report(data)), monkeypatch)
    assert not by_check(findings, "references.not-found")
    assert by_check(findings, "references.unchecked")[0].message.startswith(
        "Reference [1] was not looked up, since the lookup failed at DataCite.")


def test_doi_that_no_agency_holds_leaves_a_warning_also_while_a_registry_does_not_answer(tmp_path, cache, monkeypatch,
                                                                                        indexes):
    indexes.down = {"dois", "crossref_dois"}
    findings = run(tmp_path, cache, FakeHallucinator(report(WITH_DOI)), monkeypatch, online_titles=False)
    assert by_check(findings, "references.not-found")[0].message.endswith("was not found in DBLP")
    assert not by_check(findings, "references.unchecked")


def test_registry_keeps_the_records_of_the_requests_that_it_answered():
    def lookup(dois):
        if "10.5555/100" in dois:
            raise OSError("made-up outage")
        return {doi: Work(TITLE, ()) for doi in dois}

    dois = [f"10.5555/{number}" for number in range(120)]
    found, unanswered = references._registry_answer(lookup, dois)
    assert (sorted(found), sorted(unanswered)) == (sorted(dois[:100]), sorted(dois[100:]))


def test_registry_gets_no_further_request_once_three_requests_stay_without_an_answer():
    asked = []

    def lookup(dois):
        asked.append(len(dois))
        raise OSError("made-up outage")

    found, unanswered = references._registry_answer(lookup, [f"10.5555/{number}" for number in range(230)])
    assert (asked, found, len(unanswered)) == ([50, 50, 50], {}, 230)


def test_registry_is_asked_on_while_its_requests_fail_only_now_and_then():
    asked = []

    def lookup(dois):
        asked.append(len(dois))
        if len(asked) % 2:
            raise OSError("made-up outage")
        return {}

    _found, unanswered = references._registry_answer(lookup, [f"10.5555/{number}" for number in range(400)])
    assert (len(asked), len(unanswered)) == (8, 200)


def test_offline_run_asks_no_registry_about_a_doi(tmp_path, cache, monkeypatch, indexes):
    findings = run(tmp_path, cache, FakeHallucinator(report(WITH_DOI)), monkeypatch, online=False)
    assert indexes.nothing_asked()
    assert by_check(findings, "references.not-found")[0].message.endswith("was not found in DBLP")


def test_record_of_a_doi_under_another_title_confirms_a_reference_that_names_half_of_its_authors(tmp_path, cache,
                                                                                                 monkeypatch, indexes):
    indexes.crossref_dois[DOI.lower()] = Work("A made-up title of the journal version", ("Ada Quill", "Hana Novak"))
    findings = run(tmp_path, cache, FakeHallucinator(report(WITH_DOI)), monkeypatch, online_titles=False)
    assert not by_check(findings, "references.not-found")


@pytest.mark.parametrize(("registry", "source"), [("dois", "DataCite"), ("crossref_dois", "CrossRef")])
def test_record_of_a_doi_under_the_cited_title_with_other_authors_is_reported_as_an_author_mismatch(
        tmp_path, cache, monkeypatch, indexes, registry, source):
    getattr(indexes, registry)[DOI.lower()] = Work(TITLE, ("Petra Zeller", "Hana Novak"))
    findings = run(tmp_path, cache, FakeHallucinator(report(WITH_DOI)), monkeypatch)
    [mismatch] = by_check(findings, "references.author-mismatch")
    assert mismatch.message.endswith(f"matches a title in {source} whose authors differ: Petra Zeller, Hana Novak")
    assert not by_check(findings, "references.not-found")
    assert not by_check(findings, "references.identifier-mismatch")


def test_record_of_a_doi_under_the_main_title_of_the_entry_with_other_authors_is_an_author_mismatch(
        tmp_path, cache, monkeypatch, indexes):
    cited = f"{TITLE}: A field study"
    indexes.crossref_dois[DOI.lower()] = Work(TITLE, ("Petra Zeller",))
    entry = {"title": cited, "raw_citation": f"A. Quill, “{cited},” in Proc. Int. Conf. Softw. Eng., doi: {DOI}."}
    findings = run(tmp_path, cache, FakeHallucinator(report(entry)), monkeypatch)
    assert by_check(findings, "references.author-mismatch")[0].message.endswith("whose authors differ: Petra Zeller")


def test_record_of_a_doi_with_other_authors_leaves_the_mismatch_that_dblp_gave(tmp_path, cache, monkeypatch, indexes):
    indexes.crossref_dois[DOI.lower()] = Work(TITLE, ("Carla Marsh",))
    findings = run(tmp_path, cache, FakeHallucinator(report({**OTHER_AUTHORS, **WITH_DOI})), monkeypatch)
    [mismatch] = by_check(findings, "references.author-mismatch")
    assert mismatch.message.endswith("matches a title in DBLP whose authors differ: Petra Zeller, Hana Novak")


@pytest.mark.parametrize("authors", [("Ada Quill", "Ben Reed"), ()])
def test_record_of_a_doi_of_the_cited_authors_or_of_none_confirms_an_article_that_dblp_holds_under_other_authors(
        tmp_path, cache, monkeypatch, indexes, authors):
    indexes.crossref_dois[DOI.lower()] = Work(TITLE, authors)
    findings = run(tmp_path, cache, FakeHallucinator(report({**OTHER_AUTHORS, **WITH_DOI})), monkeypatch,
                   online_titles=False)
    assert [finding.check for finding in findings] == ["references.summary"]


@pytest.mark.parametrize(("cited", "found"), [(TITLE, 1), (f"{TITLE}: A field study", 0)])
def test_record_of_a_doi_without_authors_confirms_only_a_reference_under_nearly_its_whole_title(
        tmp_path, cache, monkeypatch, indexes, cited, found):
    indexes.crossref_dois[DOI.lower()] = Work(TITLE, ())
    entry = {"title": cited, "raw_citation": f"A. Quill, “{cited},” in Proc. Int. Conf. Softw. Eng., doi: {DOI}."}
    findings = run(tmp_path, cache, FakeHallucinator(report(entry)), monkeypatch, online_titles=False)
    assert by_check(findings, "references.summary")[0].message.endswith(f"{found} found, {1 - found} not found, "
                                                                        "0 with other authors or identifiers, 0 not "
                                                                        "looked up")
    assert not by_check(findings, "references.identifier-mismatch")


def test_record_of_the_journal_under_a_doi_does_not_confirm_a_reference(tmp_path, cache, monkeypatch, indexes):
    # In this style the name of the journal is a field of the entry, as its title is.
    journal = "Made-up Journal of Software Maintenance"
    entry = {"ref_authors": ["Quill", "Reed"],
             "raw_citation": f"Quill, A., & Reed, B. (2021). {TITLE}. {journal}, 26(3), 1–34. "
                             "https://doi.org/10.5555/mjsm"}
    indexes.crossref_dois["10.5555/mjsm"] = Work(journal, (), container=True)
    findings = run(tmp_path, cache, FakeHallucinator(report(entry)), monkeypatch, online_titles=False)
    assert by_check(findings, "references.not-found")[0].message.endswith("was not found in DBLP, CrossRef")


@pytest.mark.parametrize("authors", [("Petra Zeller",), ()])
def test_record_of_a_whole_publication_under_a_doi_confirms_a_reference_to_that_publication(
        tmp_path, cache, monkeypatch, indexes, authors):
    book = {**BOOK, "ref_authors": [*authors] or BOOK["ref_authors"],
            "raw_citation": f"{BOOK['raw_citation'][:-1]}, doi: {DOI}."}
    indexes.crossref_dois[DOI.lower()] = Work(BOOK["title"], authors, container=True)
    findings = run(tmp_path, cache, FakeHallucinator(report(book)), monkeypatch, online_titles=False)
    assert [finding.check for finding in findings] == ["references.summary"]


def test_reference_not_found_names_the_work_that_its_doi_belongs_to(tmp_path, cache, monkeypatch, indexes):
    indexes.crossref_dois[DOI.lower()] = OTHER_WORK
    findings = run(tmp_path, cache, FakeHallucinator(report(WITH_DOI)), monkeypatch, online_titles=False)
    [missing] = by_check(findings, "references.not-found")
    assert missing.message == (f'Reference [1] "{TITLE}" was not found in DBLP, CrossRef. Its DOI or arXiv ID belongs '
                               'to "Another made-up title on flaky builds"')
    assert not by_check(findings, "references.identifier-mismatch")


def test_doi_of_another_work_is_reported_for_a_reference_that_a_source_holds(tmp_path, cache, monkeypatch, indexes):
    indexes.crossref_dois[DOI.lower()] = OTHER_WORK
    findings = run(tmp_path, cache, FakeHallucinator(report(WITH_DOI), report(FOUND)), monkeypatch)
    [found] = by_check(findings, "references.identifier-mismatch")
    assert found.severity is Severity.WARNING
    assert found.message == (f'Reference [1] "{TITLE}" gives the DOI or arXiv ID of another work, "Another made-up '
                             'title on flaky builds"')
    assert not by_check(findings, "references.not-found") and not by_check(findings, "references.author-mismatch")
    assert by_check(findings, "references.summary")[0].message.endswith(
        "0 found, 0 not found, 1 with other authors or identifiers, 0 not looked up")


TECH_REPORT = {"raw_citation": f"A. Quill, “{TITLE},” Meadow Univ., Springfield, Tech. Rep. 12, 2021, doi: {DOI}.",
               "ref_authors": ["A. Quill"]}


@pytest.mark.parametrize("entry", [
    TECH_REPORT,
    {"raw_citation": f"A. Quill, “{TITLE},” Zenodo, 2021, doi: {DOI}.", "ref_authors": ["A. Quill"]},
    {"title": "Deep patch search", "raw_citation": f"A. Quill, “Deep patch search,” Meadow Press, 2021, doi: {DOI}."}])
def test_doi_of_a_work_under_a_title_of_other_words_is_reported_for_a_reference_that_is_no_article(
        tmp_path, cache, monkeypatch, indexes, entry):
    indexes.crossref_dois[DOI.lower()] = Work("Compiler warnings in an unrelated study", ("Petra Zeller",))
    findings = run(tmp_path, cache, FakeHallucinator(report(entry)), monkeypatch, online_titles=False)
    [found] = by_check(findings, "references.identifier-mismatch")
    assert found.severity is Severity.WARNING
    assert found.message.endswith('gives the DOI or arXiv ID of another work, "Compiler warnings in an unrelated study"')
    assert not by_check(findings, "references.unconfirmed") and not by_check(findings, "references.not-found")
    assert by_check(findings, "references.summary")[0].message.endswith(
        "0 found, 0 not found, 1 with other authors or identifiers, 0 not looked up")


def test_doi_of_a_record_that_shares_words_with_the_title_of_a_report_gives_the_note_alone(tmp_path, cache,
                                                                                           monkeypatch, indexes):
    indexes.crossref_dois[DOI.lower()] = Work("Data on the porting of patches to stable branches", ("Petra Zeller",))
    findings = run(tmp_path, cache, FakeHallucinator(report(TECH_REPORT)), monkeypatch, online_titles=False)
    assert [finding.check for finding in findings] == ["references.unconfirmed", "references.summary"]
    assert findings[1].message.endswith("0 found, 1 not found, 0 with other authors or identifiers, 0 not looked up")


@pytest.mark.parametrize("record", [
    Work("Proc. Int. Conf. Softw. Eng.", ("Petra Zeller",)),
    Work("Proceedings of the 43rd International Conference on Software Engineering", (), container=True),
    Work("机器学习软件工程的虚构标题", ("Petra Zeller",)),
    Work("", ("Petra Zeller",))])
def test_doi_of_the_volume_or_under_a_title_in_another_script_is_no_other_work(tmp_path, cache, monkeypatch, indexes,
                                                                               record):
    indexes.crossref_dois[DOI.lower()] = record
    findings = run(tmp_path, cache, FakeHallucinator(report(WITH_DOI), report(FOUND)), monkeypatch)
    assert not by_check(findings, "references.identifier-mismatch")
    assert by_check(findings, "references.summary")[0].message.startswith(
        "1 reference checked with online title lookups: 1 found")


def test_arxiv_record_that_bears_the_cited_title_confirms_a_reference(tmp_path, cache, monkeypatch, indexes):
    indexes.dois["10.48550/arxiv.1207.7214"] = Work(ATLAS, ("The ATLAS Collaboration",))
    findings = run(tmp_path, cache, FakeHallucinator("online-run.json"), monkeypatch, online_titles=False)
    [missing] = by_check(findings, "references.not-found")
    assert missing.message.startswith("Reference [3] ") and missing.message.endswith("was not found in DBLP, DataCite")
    assert by_check(findings, "references.summary")[0].message == (
        "3 references checked with DOI and arXiv ID lookups: 2 found, 1 not found, 0 with other authors or "
        "identifiers, 0 not looked up")


def test_arxiv_record_of_the_cited_authors_under_another_title_confirms_a_reference(tmp_path, cache, monkeypatch,
                                                                                   indexes):
    indexes.dois["10.48550/arxiv.1207.7214"] = Work("Observation of a new boson with the ATLAS detector",
                                                    ("Georges Aad", "Tatevik Abajyan", "Brad Abbott", "Jalal Abdallah"))
    findings = run(tmp_path, cache, FakeHallucinator("online-run.json"), monkeypatch, online_titles=False)
    assert [f.message.split('"')[0] for f in by_check(findings, "references.not-found")] == ["Reference [3] "]


def test_record_of_the_cited_authors_under_a_title_of_other_words_neither_confirms_nor_counts_as_another_work(
        tmp_path, cache, monkeypatch, indexes):
    indexes.crossref_dois[DOI.lower()] = Work("A real work on something else entirely", ("Ada Quill",))
    findings = run(tmp_path, cache, FakeHallucinator(report(WITH_DOI)), monkeypatch, online_titles=False)
    assert by_check(findings, "references.not-found")[0].message.endswith("was not found in DBLP, CrossRef")


def test_record_without_authors_under_a_title_of_other_words_is_another_work(tmp_path, cache, monkeypatch, indexes):
    indexes.crossref_dois[DOI.lower()] = Work("A real work on something else entirely", ())
    findings = run(tmp_path, cache, FakeHallucinator(report(WITH_DOI)), monkeypatch, online_titles=False)
    assert by_check(findings, "references.not-found")[0].message.endswith(
        'Its DOI or arXiv ID belongs to "A real work on something else entirely"')


def test_preprint_under_its_earlier_title_cited_with_et_al_is_found(tmp_path, cache, monkeypatch, indexes):
    entry = {"raw_citation": f"A. Quill et al., “{TITLE},” in Proc. Int. Conf. Softw. Eng., 2021, pp. 101–112, "
                             "arXiv:2101.00001.", "ref_authors": ["A. Quill"]}
    indexes.dois["10.48550/arxiv.2101.00001"] = Work("Porting patches: an earlier made-up title", (
        "Ada Quill", "Ben Reed", "Carla Marsh", "Dele Okafor", "Erik Lindqvist", "Hana Novak", "Petra Zeller"))
    findings = run(tmp_path, cache, FakeHallucinator(report(entry)), monkeypatch, online_titles=False)
    assert by_check(findings, "references.summary")[0].message.endswith(
        "1 found, 0 not found, 0 with other authors or identifiers, 0 not looked up")


def test_et_al_after_the_first_author_of_a_record_counts_as_its_authors_when_hallucinator_read_none(
        tmp_path, cache, monkeypatch, indexes):
    entry = {"raw_citation": f"A. Quill et al., “{TITLE},” in Proc. Int. Conf. Softw. Eng., 2021, arXiv:2101.00001.",
             "ref_authors": []}
    indexes.dois["10.48550/arxiv.2101.00001"] = Work("Porting patches: an earlier made-up title", (
        "Ada Quill", "Ben Reed", "Carla Marsh", "Dele Okafor", "Erik Lindqvist"))
    findings = run(tmp_path, cache, FakeHallucinator(report(entry)), monkeypatch, online_titles=False)
    assert not by_check(findings, "references.not-found")


def test_doi_cut_after_a_period_is_compared_with_the_record_of_the_paper_beside_that_of_its_volume(
        tmp_path, cache, monkeypatch, indexes):
    cut = {"raw_citation": f"{ENTRY[:-1]}, doi: 10.5555/3377811. 3380362."}
    assert references.parse_report(report(cut))[0].dois == ("10.5555/3377811", "10.5555/3377811.3380362")
    indexes.crossref_dois["10.5555/3377811"] = Work("Proceedings of a made-up meeting on patches", (), container=True)
    indexes.crossref_dois["10.5555/3377811.3380362"] = Work(TITLE, ("Ada Quill", "Ben Reed"))
    findings = run(tmp_path, cache, FakeHallucinator(report(cut)), monkeypatch, online_titles=False)
    assert [finding.check for finding in findings] == ["references.summary"]
    assert findings[0].message.endswith("1 found, 0 not found, 0 with other authors or identifiers, 0 not looked up")


def test_record_of_a_doi_without_the_cited_subtitle_confirms_a_reference(tmp_path, cache, monkeypatch, indexes):
    cited = f"{TITLE}: A field study"
    indexes.crossref_dois[DOI.lower()] = Work(TITLE, ("Ada Quill",))
    entry = {"title": cited, "raw_citation": f"A. Quill, “{cited},” in Proc. Int. Conf. Softw. Eng., doi: {DOI}."}
    findings = run(tmp_path, cache, FakeHallucinator(report(entry)), monkeypatch, online_titles=False)
    assert [finding.check for finding in findings] == ["references.summary"]


def test_doi_of_another_work_is_reported_also_while_openalex_does_not_answer(tmp_path, cache, monkeypatch, indexes):
    indexes.crossref_dois[DOI.lower()] = OTHER_WORK
    indexes.down = {"openalex"}
    findings = run(tmp_path, cache, FakeHallucinator(report(WITH_DOI)), monkeypatch)
    assert len(by_check(findings, "references.identifier-mismatch")) == 1
    assert not by_check(findings, "references.unchecked") and not by_check(findings, "references.not-found")
    assert by_check(findings, "references.summary")[0].message.endswith(
        "0 found, 0 not found, 1 with other authors or identifiers, 0 not looked up")


def test_reference_not_found_names_the_work_that_its_arxiv_id_belongs_to(tmp_path, cache, monkeypatch, indexes):
    indexes.dois["10.48550/arxiv.1207.7214"] = Work(ATLAS, ("The ATLAS Collaboration",))
    indexes.dois["10.48550/arxiv.1706.03762"] = Work("Attention Is All You Need", ("Ashish Vaswani", "Noam Shazeer"))
    findings = run(tmp_path, cache, FakeHallucinator("online-run.json"), monkeypatch, online_titles=False)
    [missing] = by_check(findings, "references.not-found")
    assert missing.message == ('Reference [3] "Self-healing test oracles for microservice regression suites" was not '
                               'found in DBLP, DataCite. Its DOI or arXiv ID belongs to "Attention Is All You Need"')


def test_reference_with_an_arxiv_id_is_not_looked_up_while_datacite_does_not_answer(tmp_path, cache, monkeypatch,
                                                                                   indexes):
    indexes.down = {"dois"}
    findings = run(tmp_path, cache, FakeHallucinator("online-run.json"), monkeypatch, online_titles=False)
    assert not by_check(findings, "references.not-found")
    assert by_check(findings, "references.unchecked")[0].message == (
        "References [2] and [3] were not looked up, since the lookup failed at DataCite. A later run repeats the "
        "lookup")


def test_default_run_sends_only_the_open_references_to_one_online_run(tmp_path, cache, monkeypatch):
    fake = FakeHallucinator("online-run.json", "online-titles-run.json")
    run(tmp_path, cache, fake, monkeypatch)
    local, online = fake.calls[0][0], fake.calls[1][0]
    assert set(fake.disabled(0)) == set(references.ONLINE_SOURCES) - {"DBLP"}
    assert local[local.index("--dblp-offline") + 1] == str(cache / "hallucinator" / "dblp.db")
    assert "--dblp-offline" not in online
    assert Path(online[-1]).read_text(encoding="utf-8") == (FIXTURES / "online-lookups.bib").read_text(encoding="utf-8")
    assert len(fake.calls) == 2


def test_online_run_asks_crossref_pubmed_and_the_acl_anthology(tmp_path, cache, monkeypatch):
    fake = FakeHallucinator("online-run.json", "online-titles-run.json")
    run(tmp_path, cache, fake, monkeypatch)
    assert sorted(fake.disabled(1)) == sorted([
        "arXiv", "DBLP", "Semantic Scholar", "Europe PMC", "DOI", "OpenAlex", "GovInfo", "PatentsView", "Standards",
        "Open Library", "SSRN"])


@pytest.mark.parametrize("name", ["CROSSREF_MAILTO", "HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "NO_PROXY", "https_proxy",
                                  "http_proxy", "no_proxy"])
def test_online_run_alone_gets_each_variable_of_the_user_for_crossref_and_the_proxies(tmp_path, cache, monkeypatch,
                                                                                    name):
    monkeypatch.setenv(name, "a-made-up-value")
    fake = FakeHallucinator(report({}))
    run(tmp_path, cache, fake, monkeypatch)
    local, online = fake.calls[0][1]["env"], fake.calls[1][1]["env"]
    assert name not in local and online[name] == "a-made-up-value"


def test_online_run_alone_gets_the_address_for_crossref_and_the_proxies_and_no_run_gets_a_key(tmp_path, cache,
                                                                                             monkeypatch):
    for name, value in (("S2_API_KEY", "not-a-real-key"), ("OPENALEX_KEY", "not-a-real-key"),
                        ("CROSSREF_MAILTO", "chair@example.org"), ("HTTPS_PROXY", "http://proxy.invalid:3128")):
        monkeypatch.setenv(name, value)
    fake = FakeHallucinator("online-run.json", "online-titles-run.json")
    run(tmp_path, cache, fake, monkeypatch)
    local, online = fake.calls[0][1]["env"], fake.calls[1][1]["env"]
    assert not {"S2_API_KEY", "OPENALEX_KEY", "CROSSREF_MAILTO", "HTTPS_PROXY"} & set(local)
    assert (online["CROSSREF_MAILTO"], online["HTTPS_PROXY"]) == ("chair@example.org", "http://proxy.invalid:3128")
    assert not {"S2_API_KEY", "OPENALEX_KEY"} & set(online)
    assert set(references.ONLINE_SOURCES) - set(fake.disabled(1)) == {"CrossRef", "PubMed", "ACL Anthology"}


def test_online_run_asks_no_source_that_an_offline_database_replaces(tmp_path, cache, monkeypatch):
    acl_db = tmp_path / "acl.db"
    acl_db.write_text("", encoding="utf-8")
    fake = FakeHallucinator("online-run.json", "online-titles-run.json")
    run(tmp_path, cache, fake, monkeypatch, acl_db=str(acl_db))
    assert set(references.ONLINE_SOURCES) - set(fake.disabled(1)) == {"CrossRef", "PubMed"}


def test_online_run_gets_the_timeout_of_a_run_and_ten_seconds_for_each_of_its_references(tmp_path, cache, monkeypatch):
    fake = FakeHallucinator(report({}, {"title": "A second made-up title on the porting of patches"}))
    run(tmp_path, cache, fake, monkeypatch, timeout=100)
    assert [call[1]["timeout"] for call in fake.calls] == [100, 120]


def test_run_gets_600_seconds_unless_the_template_gives_a_timeout(tmp_path, cache, monkeypatch):
    fake = FakeHallucinator(report({"status": "verified"}))
    run(tmp_path, cache, fake, monkeypatch)
    assert [call[1]["timeout"] for call in fake.calls] == [600]


def test_title_and_names_go_to_the_online_run_without_the_marks_of_bibtex(tmp_path, cache, monkeypatch):
    entry = {"title": "100% of {made-up} patches & ports #1 cost $5_000", "ref_authors": ["A. {Quill}", "B. Reed & Co"],
             "raw_citation": "A. Quill and B. Reed & Co, “100% of {made-up} patches & ports #1 cost $5_000,” in Proc. "
                             "Int. Conf. Softw. Eng., 2021."}
    run(tmp_path, cache, FakeHallucinator(report(entry)), monkeypatch)
    sent = (tmp_path / "work" / "references" / "online.bib").read_text(encoding="utf-8")
    assert "title = {100\\% of made-up patches \\& ports \\#1 cost \\$5\\_000}" in sent
    assert "author = {A. Quill and B. Reed \\& Co}" in sent


def test_online_run_keeps_the_answers_of_its_sources_in_the_cache(tmp_path, cache, monkeypatch):
    fake = FakeHallucinator("online-run.json", "online-titles-run.json")
    run(tmp_path, cache, fake, monkeypatch)
    online = fake.calls[1][0]
    assert online[online.index("--cache-path") + 1] == str(cache / "hallucinator" / "online-lookups.db")
    assert "--cache-path" not in fake.calls[0][0]


def test_online_answers_replace_the_open_references(tmp_path, cache, monkeypatch):
    findings = run(tmp_path, cache, FakeHallucinator("online-run.json", "online-titles-run.json"), monkeypatch)
    [missing] = by_check(findings, "references.not-found")
    assert missing.message == (
        'Reference [3] "Self-healing test oracles for microservice regression suites" was not found in DBLP, '
        "DataCite, Standards, ACL Anthology, Open Library, PubMed, CrossRef, OpenAlex")
    assert by_check(findings, "references.summary")[0].message == (
        "3 references checked with online title lookups: 2 found, 1 not found, 0 with other authors or identifiers, "
        "0 not looked up")


def test_no_online_lookup_when_the_local_databases_confirm_every_reference(tmp_path, cache, monkeypatch, indexes):
    confirmed = json.loads((FIXTURES / "online-run.json").read_text(encoding="utf-8"))
    for entry in confirmed[0]["references"]:
        entry["status"] = "verified"
    fake = FakeHallucinator(confirmed)
    run(tmp_path, cache, fake, monkeypatch)
    assert len(fake.calls) == 1
    assert indexes.nothing_asked()


def test_online_false_keeps_titles_offline_even_when_online_titles_is_true(tmp_path, cache, monkeypatch, indexes):
    fake = FakeHallucinator("offline-run.json")
    run(tmp_path, cache, fake, monkeypatch, online=False, online_titles=True)
    assert set(fake.disabled()) == set(references.ONLINE_SOURCES) - {"DBLP"}
    assert len(fake.calls) == 1
    assert indexes.nothing_asked()


@pytest.mark.parametrize("option", ["online", "online_titles"])
@pytest.mark.parametrize("value", ["false", "no", "off", "true", 0, 1, None])
def test_online_option_that_is_no_boolean_stops_the_check_before_anything_is_sent(tmp_path, cache, monkeypatch,
                                                                                  indexes, option, value):
    fake = FakeHallucinator("online-run.json")
    with pytest.raises(profile_module.ProfileError, match=f"references.{option} must be true or false, not "):
        run(tmp_path, cache, fake, monkeypatch, **{option: value})
    assert fake.calls == [] and indexes.nothing_asked()


def test_datacite_record_with_the_title_and_a_cited_author_confirms_a_reference(tmp_path, cache, monkeypatch, indexes):
    indexes.datacite[TITLE] = [Work("Another made-up title on patches", ("Ada Quill",)), Work(TITLE, ("Ada Quill",))]
    findings = run(tmp_path, cache, FakeHallucinator(report({})), monkeypatch)
    assert not by_check(findings, "references.not-found")
    assert indexes.asked["openalex"] == []


def test_openalex_record_with_the_title_and_a_cited_author_confirms_a_reference(tmp_path, cache, monkeypatch, indexes):
    indexes.openalex[TITLE] = [Work(TITLE.upper(), ("Ben Reed", "Hana Novak"))]
    findings = run(tmp_path, cache, FakeHallucinator(report({})), monkeypatch)
    assert not by_check(findings, "references.not-found")
    assert by_check(findings, "references.summary")[0].message.startswith(
        "1 reference checked with online title lookups: 1 found")


def test_index_record_of_other_authors_under_the_title_is_reported_as_an_author_mismatch(tmp_path, cache, monkeypatch,
                                                                                        indexes):
    indexes.datacite[TITLE] = [Work(TITLE, ("Petra Zeller",))]
    indexes.openalex[TITLE] = [Work(TITLE, ("Hana Novak",))]
    findings = run(tmp_path, cache, FakeHallucinator(report({})), monkeypatch)
    [mismatch] = by_check(findings, "references.author-mismatch")
    assert mismatch.message.endswith("matches a title in DataCite whose authors differ: Petra Zeller")
    assert not by_check(findings, "references.not-found")


@pytest.mark.parametrize(("authors", "entry"), [
    (("Bo An", "Petra Zeller"), ENTRY.replace(TITLE, "An empirical made-up study of ported patches")),
    (("Hoh Peter In", "Petra Zeller"), ENTRY),
    (("Sindhu A", "Petra Zeller"), ENTRY),
    (("Jonathan May", "Petra Zeller"), ENTRY.replace("2021", "May 2021")),
    (("Petra Zeller", "Hana Novak", "Yan Al"), ENTRY.replace("A. Quill and B. Reed", "A. Quill et al."))])
def test_record_of_other_authors_whose_family_name_is_a_word_of_the_entry_does_not_confirm(
        tmp_path, cache, monkeypatch, indexes, authors, entry):
    title = entry.split("“")[1].split(",”")[0]
    indexes.openalex[title] = [Work(title, authors)]
    findings = run(tmp_path, cache, FakeHallucinator(report({"title": title, "raw_citation": entry})), monkeypatch)
    assert len(by_check(findings, "references.author-mismatch")) == 1
    assert by_check(findings, "references.summary")[0].message.startswith(
        "1 reference checked with online title lookups: 0 found")


def test_work_cited_under_its_consortium_is_found_in_a_record_that_names_the_members(tmp_path, cache, monkeypatch,
                                                                                    indexes):
    entry = {"ref_authors": ["The Madeup Collaboration"],
             "raw_citation": ENTRY.replace("A. Quill and B. Reed", "The Made-up Collaboration")}
    indexes.openalex[TITLE] = [Work(TITLE, ("Hana Novak", "Petra Zeller", "Carla Marsh"))]
    findings = run(tmp_path, cache, FakeHallucinator(report(entry)), monkeypatch)
    assert [finding.check for finding in findings] == ["references.summary"]


@pytest.mark.parametrize("author", ["The Made-up Collaboration", "Madeup-AI"])
def test_work_cited_under_its_members_is_found_in_a_record_that_names_the_consortium_or_the_company(
        tmp_path, cache, monkeypatch, indexes, author):
    indexes.openalex[TITLE] = [Work(TITLE, (author,))]
    findings = run(tmp_path, cache, FakeHallucinator(report({})), monkeypatch)
    assert [finding.check for finding in findings] == ["references.summary"]


def test_index_record_with_the_family_name_first_confirms_a_reference(tmp_path, cache, monkeypatch, indexes):
    entry = {"raw_citation": ENTRY.replace("A. Quill and B. Reed", "W. Zhang and L. Chen"),
             "ref_authors": ["W. Zhang", "L. Chen"]}
    indexes.openalex[TITLE] = [Work(TITLE, ("Zhang Wei", "Chen Li"))]
    findings = run(tmp_path, cache, FakeHallucinator(report(entry)), monkeypatch)
    assert not by_check(findings, "references.not-found") and not by_check(findings, "references.author-mismatch")


@pytest.mark.parametrize("authors", [(), ("张伟", "陈丽")])
def test_index_record_without_an_author_to_compare_confirms_a_reference_by_its_title(tmp_path, cache, monkeypatch,
                                                                                    indexes, authors):
    indexes.openalex[TITLE] = [Work(TITLE, authors)]
    findings = run(tmp_path, cache, FakeHallucinator(report({})), monkeypatch)
    assert by_check(findings, "references.summary")[0].message.startswith(
        "1 reference checked with online title lookups: 1 found")


def test_index_record_without_an_author_under_the_main_title_alone_does_not_confirm_a_reference(
        tmp_path, cache, monkeypatch, indexes):
    cited = f"{TITLE}: A field study"
    indexes.openalex[cited] = [Work(TITLE, ())]
    entry = {"title": cited, "raw_citation": ENTRY.replace(TITLE, cited)}
    findings = run(tmp_path, cache, FakeHallucinator(report(entry)), monkeypatch)
    assert len(by_check(findings, "references.not-found")) == 1


def test_index_record_without_an_author_does_not_confirm_beside_a_record_of_other_authors_under_the_main_title(
        tmp_path, cache, monkeypatch, indexes):
    cited = f"{TITLE}: A field study"
    indexes.openalex[cited] = [Work(cited, ()), Work(TITLE, ("Petra Zeller",))]
    entry = {"title": cited, "raw_citation": ENTRY.replace(TITLE, cited)}
    findings = run(tmp_path, cache, FakeHallucinator(report(entry)), monkeypatch)
    assert len(by_check(findings, "references.not-found")) == 1
    assert not by_check(findings, "references.author-mismatch")


def test_index_record_without_an_author_does_not_confirm_a_title_that_dblp_holds_under_other_authors(
        tmp_path, cache, monkeypatch, indexes):
    indexes.openalex[TITLE] = [Work(TITLE, ())]
    findings = run(tmp_path, cache, FakeHallucinator(report(OTHER_AUTHORS)), monkeypatch)
    assert len(by_check(findings, "references.author-mismatch")) == 1


def test_index_record_of_the_cited_authors_confirms_beside_a_record_of_other_authors(tmp_path, cache, monkeypatch,
                                                                                    indexes):
    indexes.openalex[TITLE] = [Work(TITLE, ("Petra Zeller",)), Work(TITLE, ()), Work(TITLE, ("Ada Quill",))]
    findings = run(tmp_path, cache, FakeHallucinator(report({})), monkeypatch)
    assert not by_check(findings, "references.author-mismatch") and not by_check(findings, "references.not-found")


def test_index_record_without_the_cited_subtitle_confirms_a_reference(tmp_path, cache, monkeypatch, indexes):
    cited = f"{TITLE}: A field study"
    indexes.openalex[cited] = [Work(TITLE, ("Ada Quill", "Ben Reed"))]
    entry = {"title": cited, "raw_citation": ENTRY.replace(TITLE, cited)}
    findings = run(tmp_path, cache, FakeHallucinator(report(entry)), monkeypatch)
    assert not by_check(findings, "references.not-found")


def test_index_record_with_a_subtitle_that_the_entry_leaves_out_confirms_a_reference(tmp_path, cache, monkeypatch,
                                                                                    indexes):
    indexes.openalex[TITLE] = [Work(f"{TITLE}: A field study", ("Ada Quill", "Ben Reed"))]
    findings = run(tmp_path, cache, FakeHallucinator(report({})), monkeypatch)
    assert not by_check(findings, "references.not-found")


def test_lookup_that_ends_early_leaves_a_reference_not_looked_up_and_the_check_running(tmp_path, cache, monkeypatch,
                                                                                      indexes):
    def cut(title):
        raise http.client.IncompleteRead(b'{"results": [', 987)

    monkeypatch.setattr(references.open_indexes, "openalex_works", cut)
    findings = run(tmp_path, cache, FakeHallucinator(report({})), monkeypatch)
    assert by_check(findings, "references.unchecked")[0].message.startswith(
        "Reference [1] was not looked up, since the lookup failed at OpenAlex.")


def test_second_run_asks_no_index_again_for_a_title_that_the_first_run_looked_up(tmp_path, cache, monkeypatch, indexes):
    first = run(tmp_path, cache, FakeHallucinator(report({})), monkeypatch)
    asked = {name: list(titles) for name, titles in indexes.asked.items()}
    second = run(tmp_path, cache, FakeHallucinator(report({})), monkeypatch)
    assert asked["openalex"] == [TITLE, "A made-up title on", "the porting of patches"]
    assert (indexes.asked["openalex"], indexes.asked["datacite"]) == (asked["openalex"], asked["datacite"])
    assert [finding.message for finding in first] == [finding.message for finding in second]


def test_lookup_that_failed_is_asked_again_in_the_next_run(tmp_path, cache, monkeypatch, indexes):
    indexes.down = {"openalex"}
    run(tmp_path, cache, FakeHallucinator(report({})), monkeypatch)
    indexes.down = set()
    findings = run(tmp_path, cache, FakeHallucinator(report({})), monkeypatch)
    assert indexes.asked["openalex"] == [TITLE, TITLE, "A made-up title on", "the porting of patches"]
    assert len(by_check(findings, "references.not-found")) == 1


def test_index_record_of_a_cited_author_under_another_title_does_not_confirm_a_reference(tmp_path, cache, monkeypatch,
                                                                                        indexes):
    indexes.datacite[TITLE] = [Work("Another made-up title on the porting of patches", ("Ada Quill", "Ben Reed"))]
    findings = run(tmp_path, cache, FakeHallucinator(report({})), monkeypatch)
    assert len(by_check(findings, "references.not-found")) == 1


def test_openalex_gets_only_the_references_that_the_check_would_report(tmp_path, cache, monkeypatch, indexes):
    findings = run(tmp_path, cache, FakeHallucinator(report({}, BOOK, SHORT)), monkeypatch)
    assert sorted(indexes.asked["datacite"]) == sorted([TITLE, BOOK["title"]])
    assert indexes.asked["openalex"] == [TITLE, "A made-up title on", "the porting of patches"]
    assert [f.message.split('"')[0] for f in by_check(findings, "references.not-found")] == ["Reference [1] "]


def test_online_run_gets_only_articles_and_papers(tmp_path, cache, monkeypatch):
    fake = FakeHallucinator(report({}, BOOK, SHORT), report({}))
    run(tmp_path, cache, fake, monkeypatch)
    sent = (tmp_path / "work" / "references" / "online.bib").read_text(encoding="utf-8")
    assert sent.count("@misc") == 1 and TITLE in sent and BOOK["title"] not in sent


def test_openalex_record_under_half_of_a_title_confirms_a_reference_with_one_wrong_word(tmp_path, cache, monkeypatch,
                                                                                        indexes):
    # The first half of the cited title holds the record, while a hyphen that a line end left hides it from the whole.
    cited = "A made-up title on the por-ting of patches"
    indexes.openalex["A made-up title on"] = [Work("A made-up title on flaky builds", ("Ada Quill",)),
                                              Work(TITLE, ("Ada Quill", "Ben Reed"))]
    entry = {"title": cited, "raw_citation": ENTRY.replace(TITLE, cited)}
    findings = run(tmp_path, cache, FakeHallucinator(report(entry)), monkeypatch)
    assert indexes.asked["openalex"] == [cited, "A made-up title on"]
    assert not by_check(findings, "references.not-found")


def test_title_of_five_to_seven_words_goes_to_openalex_also_as_its_first_and_its_last_four_words(tmp_path, cache,
                                                                                                monkeypatch, indexes):
    cited = "A made-up title on stable patches"
    run(tmp_path, cache, FakeHallucinator(report({"title": cited, "raw_citation": ENTRY.replace(TITLE, cited)})),
        monkeypatch)
    assert indexes.asked["openalex"] == [cited, "A made-up title on", "title on stable patches"]


def test_title_of_four_words_goes_to_openalex_only_as_a_whole(tmp_path, cache, monkeypatch, indexes):
    cited = "Made-up patches of stable"
    run(tmp_path, cache, FakeHallucinator(report({"title": cited, "raw_citation": ENTRY.replace(TITLE, cited)})),
        monkeypatch)
    assert indexes.asked["openalex"] == [cited]


def test_title_that_hallucinator_read_with_a_part_of_the_venue_is_found_under_its_first_words(tmp_path, cache,
                                                                                             monkeypatch, indexes):
    real = "Do stable branches get fixes?"
    entry = {"title": f"{real}” in Proc", "ref_authors": ["C. Marsh"],
             "raw_citation": f"C. Marsh, “{real}” in Proc. Int. Conf. Softw. Eng., 2022, pp. 44–55."}
    indexes.openalex["Do stable branches get"] = [Work(real, ("Carla Marsh",))]
    findings = run(tmp_path, cache, FakeHallucinator(report(entry)), monkeypatch)
    assert not by_check(findings, "references.not-found")


def test_openreview_gets_only_the_articles_of_the_last_two_years_that_the_check_would_report(tmp_path, cache,
                                                                                             monkeypatch, indexes):
    year = datetime.date.today().year
    recent = {"title": "A recent made-up title on the porting of patches",
              "raw_citation": "A. Quill, “A recent made-up title on the porting of patches,” in Proc. Int. Conf. "
                              f"Softw. Eng., {year}."}
    recent_book = {**BOOK, "raw_citation": BOOK["raw_citation"].replace("2019", str(year))}
    run(tmp_path, cache, FakeHallucinator(report({}, BOOK, recent, recent_book)), monkeypatch)
    assert indexes.asked["openreview"] == [recent["title"]]


def test_openreview_record_with_the_title_and_a_cited_author_confirms_a_recent_paper(tmp_path, cache, monkeypatch,
                                                                                    indexes):
    entry = {"raw_citation": ENTRY.replace("2021", str(datetime.date.today().year))}
    indexes.openreview[TITLE] = [Work(TITLE, ("Ada Quill", "Ben Reed"))]
    findings = run(tmp_path, cache, FakeHallucinator(report(entry)), monkeypatch)
    assert not by_check(findings, "references.not-found")
    assert by_check(findings, "references.summary")[0].message.startswith(
        "1 reference checked with online title lookups: 1 found")


def test_openreview_paper_under_review_which_names_no_author_confirms_a_recent_paper(tmp_path, cache, monkeypatch,
                                                                                    indexes):
    entry = {"raw_citation": ENTRY.replace("2021", str(datetime.date.today().year))}
    indexes.openreview[TITLE] = [Work(TITLE, ())]
    findings = run(tmp_path, cache, FakeHallucinator(report(entry)), monkeypatch)
    assert [finding.check for finding in findings] == ["references.summary"]


def test_dash_for_the_authors_of_the_entry_before_takes_the_names_that_hallucinator_read(tmp_path, cache, monkeypatch,
                                                                                        indexes):
    indexes.datacite[TITLE] = [Work(TITLE, ("Ada Quill", "Ben Reed"))]
    dash = {"raw_citation": f"——, “{TITLE},” in Proc. Int. Conf. Softw. Eng., 2021, pp. 101–112."}
    findings = run(tmp_path, cache, FakeHallucinator(report(dash)), monkeypatch)
    assert not by_check(findings, "references.not-found")


def test_article_with_a_web_address_that_hallucinator_passes_over_is_looked_up(tmp_path, cache, monkeypatch, indexes):
    passed = {"status": "skipped", "url_check_skipped": True,
              "raw_citation": f"{ENTRY} [Online]. Available: http://www.example.org/stable/2282330"}
    fake = FakeHallucinator(report(passed))
    findings = run(tmp_path, cache, fake, monkeypatch)
    assert len(fake.calls) == 2 and indexes.asked["openalex"][0] == TITLE
    assert by_check(findings, "references.not-found")[0].message.endswith(
        "was not found in DBLP, CrossRef, DataCite, OpenAlex")


def passed_over(venue: str) -> references.Reference:
    """Return an entry with a venue and a web address that Hallucinator passed over, as PeerCheck reads it."""
    return parsed(status="skipped", url_check_skipped=True,
                  raw_citation=f"A. Quill, “{TITLE},” {venue}. [Online]. Available: https://www.example.org/quill")


@pytest.mark.parametrize("venue", [
    "in Proceedings of the Made-up Meeting, 2021", "in Proc. Made-up Meeting, 2021", "Made-up Transactions, 2021",
    "Made-up Trans., 2021", "Made-up Review, vol. 3, 2021", "Made-up Review, 2021, pp. 3",
    "Made-up Review, 2021, Article 12", "Made-up Review, 2021, 101–112", "Made-up Journal, 2021, doi: 10.5555/1",
    "Made-up Journal, 2021, arXiv:2101.00001", "Made-up Softw. Eng. 26(3), 1-34 (2021)"])
def test_entry_with_a_web_address_and_a_mark_of_a_published_article_is_looked_up(venue):
    assert passed_over(venue).status == "not_found"


@pytest.mark.parametrize("venue", [
    "Made-up Developer Conference, 2021", "in Int. Conf. Made-up Patches, 2021", "Made-up Symposium, 2021",
    "Made-up Symp., 2021", "Made-up Kernel Workshop, 2021", "The Made-up Street Journal, Mar. 2021",
    "Made-up Magazine, 2021", "Made-up Letters, 2021", "CoRR, 2021", "arXiv preprint, 2021", "in ICSE, 2021",
    "Made-up Journal, release range: 14.1.1–15.0.0"])
def test_entry_with_a_web_address_and_only_the_name_of_an_event_or_a_periodical_is_passed_over(venue):
    ref = passed_over(venue)
    assert references._is_article(ref) and ref.status == "skipped"


def test_word_of_a_published_article_in_the_title_of_an_entry_with_a_web_address_leaves_it_passed_over():
    title = "A thousand transactions per second, vol. 2"
    passed = parsed(status="skipped", url_check_skipped=True, title=title,
                    raw_citation=f"A. Quill, “{title},” Made-up Magazine, 2021. https://www.example.org/quill")
    assert passed.status == "skipped"


def test_news_item_with_a_web_address_that_hallucinator_passes_over_gets_the_note_and_no_warning(
        tmp_path, cache, monkeypatch, indexes):
    news = {"status": "skipped", "url_check_skipped": True,
            "raw_citation": f"A. Quill, “{TITLE},” The Made-up Street Journal, Mar. 2021. [Online]. Available: "
                            "https://www.example.org/news/quill"}
    fake = FakeHallucinator(report(news))
    findings = run(tmp_path, cache, fake, monkeypatch)
    assert len(fake.calls) == 1 and indexes.nothing_asked()
    assert [finding.check for finding in findings] == ["references.unchecked", "references.summary"]


def test_web_page_and_short_title_that_hallucinator_passes_over_get_one_note(tmp_path, cache, monkeypatch, indexes):
    page = {"status": "skipped", "url_check_skipped": True, "title": "The made-up kernel documentation",
            "raw_citation": "Made-up Kernel Organization, “The made-up kernel documentation,” 2021. [Online]. "
                            "Available: http://www.example.org/doc"}
    short = {"status": "skipped", "skip_reason": "short_title", "title": "Deep patch search", "raw_citation": "",
             "ref_authors": [], "db_results": []}
    fake = FakeHallucinator(report(page, short))
    findings = run(tmp_path, cache, fake, monkeypatch)
    assert len(fake.calls) == 1 and indexes.nothing_asked()
    note = ("References [1] and [2] were not looked up. Such an entry hides a work for the review, names a web page, "
            "or bears no title of four words or more")
    summary = ("2 references checked with online title lookups: 0 found, 0 not found, 0 with other authors or "
               "identifiers, 2 not looked up")
    assert [(finding.check, finding.message) for finding in findings] == [("references.unchecked", note),
                                                                          ("references.summary", summary)]
    assert findings[0].evidence == "[1] The made-up kernel documentation; [2] Deep patch search"


def test_book_whose_title_dblp_holds_under_other_authors_gets_the_note_and_no_warning(tmp_path, cache, monkeypatch):
    other = {**BOOK, **OTHER_AUTHORS, "found_authors": ["Hana Novak", "Carla Marsh"]}
    findings = run(tmp_path, cache, FakeHallucinator(report(other)), monkeypatch, online=False)
    assert by_check(findings, "references.unconfirmed")[0].message.startswith("Reference [1] was not found, as is")
    assert not by_check(findings, "references.author-mismatch")
    assert by_check(findings, "references.summary")[0].message.endswith(
        "0 found, 1 not found, 0 with other authors or identifiers, 0 not looked up")


def test_openalex_record_of_the_cited_authors_confirms_an_article_that_dblp_holds_under_other_authors(tmp_path, cache,
                                                                                                     monkeypatch,
                                                                                                     indexes):
    indexes.openalex[TITLE] = [Work(TITLE, ("Ada Quill", "Ben Reed"))]
    online = report({"db_results": [{"db": "CrossRef", "status": "no_match"}]})
    findings = run(tmp_path, cache, FakeHallucinator(report(OTHER_AUTHORS), online), monkeypatch)
    assert not by_check(findings, "references.author-mismatch")
    assert by_check(findings, "references.summary")[0].message.startswith(
        "1 reference checked with online title lookups: 1 found")


def test_book_and_short_title_that_are_not_found_get_one_note_and_no_warning(tmp_path, cache, monkeypatch):
    findings = run(tmp_path, cache, FakeHallucinator(report(BOOK, SHORT)), monkeypatch, online=False)
    [note] = by_check(findings, "references.unconfirmed")
    assert note.severity is Severity.INFO
    assert note.message == ("References [1] and [2] were not found, as is common for a book, a report, a talk, a web "
                            "page, a dataset, a title of fewer than four words, or a work registered in another script "
                            "or at another DOI agency")
    assert note.evidence == "[1] Maintaining Stable Releases: A Field Guide; [2] Deep patch search"
    assert not by_check(findings, "references.not-found")


def test_reference_that_datacite_does_not_answer_is_reported_with_the_sources_that_answered(tmp_path, cache,
                                                                                           monkeypatch, indexes):
    indexes.down = {"datacite"}
    findings = run(tmp_path, cache, FakeHallucinator(report({})), monkeypatch)
    [missing] = by_check(findings, "references.not-found")
    assert missing.message.endswith("was not found in DBLP, CrossRef, OpenAlex")


def test_reference_that_openalex_does_not_answer_gets_a_note_and_no_warning(tmp_path, cache, monkeypatch, indexes):
    indexes.down = {"openalex"}
    findings = run(tmp_path, cache, FakeHallucinator(report({})), monkeypatch)
    [note] = by_check(findings, "references.unchecked")
    assert note.message == ("Reference [1] was not looked up, since the lookup failed at OpenAlex. A later run repeats "
                            "the lookup")
    assert not by_check(findings, "references.not-found")


def test_record_of_other_authors_is_not_reported_while_openalex_does_not_answer(tmp_path, cache, monkeypatch, indexes):
    # OpenAlex may hold the cited work under the same title.
    indexes.down = {"openalex"}
    findings = run(tmp_path, cache, FakeHallucinator(report(OTHER_AUTHORS)), monkeypatch)
    assert not by_check(findings, "references.author-mismatch")
    assert by_check(findings, "references.unchecked")[0].message == (
        "Reference [1] was not looked up, since the lookup failed at OpenAlex. A later run repeats the lookup")
    assert by_check(findings, "references.summary")[0].message.endswith(
        "0 found, 0 not found, 0 with other authors or identifiers, 1 not looked up")


def test_record_of_other_authors_is_not_reported_while_the_registry_of_the_doi_does_not_answer(tmp_path, cache,
                                                                                              monkeypatch, indexes):
    indexes.down = {"crossref_dois"}
    indexes.agencies[DOI.lower()] = "Crossref"
    findings = run(tmp_path, cache, FakeHallucinator(report({**OTHER_AUTHORS, **WITH_DOI})), monkeypatch,
                   online_titles=False)
    assert not by_check(findings, "references.author-mismatch")
    assert by_check(findings, "references.unchecked")[0].message.startswith(
        "Reference [1] was not looked up, since the lookup failed at CrossRef.")


def test_doi_of_another_work_is_reported_without_the_other_authors_while_openalex_does_not_answer(
        tmp_path, cache, monkeypatch, indexes):
    indexes.crossref_dois[DOI.lower()] = OTHER_WORK
    indexes.down = {"openalex"}
    findings = run(tmp_path, cache, FakeHallucinator(report({**OTHER_AUTHORS, **WITH_DOI})), monkeypatch)
    assert len(by_check(findings, "references.identifier-mismatch")) == 1
    assert not by_check(findings, "references.author-mismatch") and not by_check(findings, "references.unchecked")


def test_index_gets_no_further_request_once_three_requests_stay_without_an_answer(tmp_path, cache, monkeypatch,
                                                                                 indexes):
    indexes.down = {"openalex"}
    entries = [{"title": f"{TITLE} in project {number}"} for number in range(1, 10)]
    findings = run(tmp_path, cache, FakeHallucinator(report(*entries)), monkeypatch)
    assert len(indexes.asked["datacite"]) == 9
    assert len(indexes.asked["openalex"]) == references.INDEX_RUNS
    assert by_check(findings, "references.summary")[0].message.endswith("0 not found, 0 with other authors or "
                                                                        "identifiers, 9 not looked up")


def test_index_is_asked_on_while_its_requests_fail_only_now_and_then(tmp_path):
    refs = [parsed(title=f"{TITLE} in project {number}") for number in range(20)]
    asked = []

    def works_of(title):
        asked.append(title)
        if title.split()[-1] in ("0", "4", "8", "12"):
            raise OSError("made-up outage")
        return []

    answers = references._confirmed_by_title(refs, works_of, "OpenAlex", references._is_open,
                                             LookupCache(tmp_path / "kept.json"))
    assert len(asked) == 20
    assert [ref.failed for ref in answers].count(("OpenAlex",)) == 4


def test_kept_answer_confirms_a_reference_after_the_index_stopped_answering_and_brings_no_further_request(tmp_path):
    refs = [parsed(title=f"{TITLE} in project {number}") for number in range(12)]
    kept = LookupCache(tmp_path / "kept.json")
    kept.works("OpenAlex", refs[5].title, lambda title: [Work(title, ("Ada Quill", "Ben Reed"))])
    asked = []

    def works_of(title):
        asked.append(title)
        raise OSError("made-up outage")

    answers = references._confirmed_by_title(refs, works_of, "OpenAlex", references._is_open, kept)
    assert len(asked) == references.INDEX_RUNS
    assert [ref.status for ref in answers] == ["not_found"] * 5 + ["verified"] + ["not_found"] * 6
    assert [ref.failed for ref in answers].count(("OpenAlex",)) == 11


@pytest.mark.parametrize(("seconds_over", "requests", "not_looked_up"), [(-1, 11, 0), (0, 4, 7)])
def test_index_gets_no_further_request_once_its_seconds_for_the_titles_of_a_run_are_over(
        tmp_path, monkeypatch, seconds_over, requests, not_looked_up):
    refs = [parsed(title=f"{TITLE} in project {number}") for number in range(12)]
    kept = LookupCache(tmp_path / "kept.json")
    kept.works("OpenAlex", refs[9].title, lambda title: [Work(title, ("Ada Quill", "Ben Reed"))])
    clock, asked = [1000.0], []
    monkeypatch.setattr(references.open_indexes.time, "monotonic", lambda: clock[0])

    def works_of(title):
        asked.append(title)
        if title == refs[0].title:
            clock[0] += references.INDEX_SECONDS * len(refs) + seconds_over
        return []

    answers = references._confirmed_by_title(refs, works_of, "OpenAlex", references._is_open, kept)
    assert len(asked) == requests
    assert [ref.failed for ref in answers].count(("OpenAlex",)) == not_looked_up
    assert answers[9].status == "verified"


def test_seconds_of_an_index_for_one_title_allow_for_the_pace_of_openreview():
    assert references.INDEX_SECONDS == references.open_indexes.TIMEOUT / references.INDEX_RUNS == 5
    assert references.INDEX_SECONDS > references.open_indexes.OPENREVIEW_PACE.window / 20


def test_dblp_record_of_other_authors_is_no_mismatch_once_an_online_source_confirms_the_reference(tmp_path, cache,
                                                                                                 monkeypatch):
    online = report({"status": "verified", "source": "CrossRef", "found_authors": ["Ada Quill", "Ben Reed"],
                     "db_results": [{"db": "CrossRef", "status": "match"}]})
    fake = FakeHallucinator(report(OTHER_AUTHORS), online)
    findings = run(tmp_path, cache, fake, monkeypatch)
    assert len(fake.calls) == 2
    assert not by_check(findings, "references.author-mismatch")


def test_dblp_record_of_other_authors_stays_a_mismatch_when_no_online_source_holds_the_title(tmp_path, cache,
                                                                                            monkeypatch):
    online = report({"db_results": [{"db": "CrossRef", "status": "no_match"}]})
    findings = run(tmp_path, cache, FakeHallucinator(report(OTHER_AUTHORS), online), monkeypatch)
    [mismatch] = by_check(findings, "references.author-mismatch")
    assert mismatch.message.endswith("matches a title in DBLP whose authors differ: Petra Zeller, Hana Novak")
    assert not by_check(findings, "references.not-found")


def test_crossref_record_that_hallucinator_set_aside_in_the_online_run_confirms_a_reference(tmp_path, cache,
                                                                                           monkeypatch):
    title = "Porting patches between branches"
    entry = {"title": title, "ref_authors": ["A. Quill", "B. Reed", "C. Marsh"],
             "raw_citation": f"A. Quill, B. Reed, and C. Marsh, “{title},” in Proc. Int. Conf. Softw. Eng., 2021."}
    set_aside = {"db": "CrossRef", "status": "author_mismatch", "authors": ["Ada Quill"]}
    online = report({**entry, "db_results": [set_aside]})
    findings = run(tmp_path, cache, FakeHallucinator(report(entry), online), monkeypatch)
    assert [finding.check for finding in findings] == ["references.summary"]


def test_crossref_record_that_the_online_run_accepts_for_one_of_three_cited_authors_is_an_author_mismatch(
        tmp_path, cache, monkeypatch):
    entry = {key: ACCEPTED_FOR_ONE_AUTHOR[key] for key in ("ref_authors", "raw_citation")}
    accepted = {**entry, "status": "verified", "source": "CrossRef", "found_authors": ["Ada Quill", "Petra Zeller"],
                "db_results": [{"db": "CrossRef", "status": "match"}]}
    findings = run(tmp_path, cache, FakeHallucinator(report(entry), report(accepted)), monkeypatch)
    [mismatch] = by_check(findings, "references.author-mismatch")
    assert mismatch.message.endswith("matches a title in CrossRef whose authors differ: Ada Quill, Petra Zeller")


def test_record_that_the_online_run_accepts_confirms_an_entry_that_names_its_authors_where_hallucinator_read_none(
        tmp_path, cache, monkeypatch):
    # The online run gets the title and no author, therefore its report holds no author to compare with the record.
    accepted = {**FOUND, "ref_authors": [], "raw_citation": TITLE}
    findings = run(tmp_path, cache, FakeHallucinator(report({"ref_authors": []}), report(accepted)), monkeypatch)
    assert [finding.check for finding in findings] == ["references.summary"]


def test_reference_that_the_online_run_passes_over_for_its_title_gets_the_note_on_such_entries(tmp_path, cache,
                                                                                              monkeypatch):
    passed = report({"status": "skipped", "skip_reason": "short_title", "db_results": []})
    fake = FakeHallucinator(report({}), passed)
    findings = run(tmp_path, cache, fake, monkeypatch)
    assert len(fake.calls) == 2
    note = ("Reference [1] was not looked up. Such an entry hides a work for the review, names a web page, or bears "
            "no title of four words or more")
    assert [(finding.check, finding.message) for finding in findings[:-1]] == [("references.unchecked", note)]


def test_reference_that_the_online_run_passes_over_is_found_once_an_index_confirms_it(tmp_path, cache, monkeypatch,
                                                                                      indexes):
    indexes.openalex[TITLE] = [Work(TITLE, ("Ada Quill", "Ben Reed"))]
    passed = report({"status": "skipped", "skip_reason": "short_title", "db_results": []})
    findings = run(tmp_path, cache, FakeHallucinator(report({}), passed), monkeypatch)
    assert [finding.check for finding in findings] == ["references.summary"]


def test_reference_that_the_online_run_passes_over_keeps_the_warning_that_names_the_work_of_its_doi(
        tmp_path, cache, monkeypatch, indexes):
    indexes.crossref_dois[DOI.lower()] = OTHER_WORK
    passed = report({"status": "skipped", "skip_reason": "short_title", "db_results": []})
    findings = run(tmp_path, cache, FakeHallucinator(report(WITH_DOI), passed), monkeypatch)
    [missing] = by_check(findings, "references.not-found")
    assert missing.message.endswith('Its DOI or arXiv ID belongs to "Another made-up title on flaky builds"')
    assert not by_check(findings, "references.unchecked")


@pytest.mark.parametrize("online", [
    [{"references": []}],
    report({"db_results": [{"db": "CrossRef", "status": "skipped"}, {"db": "PubMed", "status": "no_match"}]})])
def test_reference_that_crossref_was_not_asked_about_is_not_looked_up(tmp_path, cache, monkeypatch, online):
    fake = FakeHallucinator(report({}), online)
    findings = run(tmp_path, cache, fake, monkeypatch)
    assert len(fake.calls) == 2
    assert not by_check(findings, "references.not-found")
    assert by_check(findings, "references.unchecked")[0].message.startswith(
        "Reference [1] was not looked up, since the lookup failed at CrossRef.")


def test_answer_of_the_online_run_under_the_title_of_another_entry_says_nothing_about_a_reference(tmp_path, cache,
                                                                                                 monkeypatch):
    # The .bib reader of Hallucinator numbers the entries that it could parse, so an entry that it drops moves each
    # later answer one number down.
    second = "A second made-up title on the review of fixes"
    local = report({}, {"title": second, "raw_citation": ENTRY.replace(TITLE, second)})
    moved = report({**FOUND, "title": second, "raw_citation": f"A. Quill, B. Reed. {second}"})
    findings = run(tmp_path, cache, FakeHallucinator(local, moved), monkeypatch)
    assert by_check(findings, "references.unchecked")[0].message.startswith(
        "References [1] and [2] were not looked up, since the lookup failed at CrossRef.")
    assert by_check(findings, "references.summary")[0].message.endswith(
        "0 found, 0 not found, 0 with other authors or identifiers, 2 not looked up")


def test_answer_of_the_online_run_counts_under_a_title_that_differs_in_its_marks_alone(tmp_path, cache, monkeypatch):
    marked = "A made-up title on the porting of patches: 100% & more_"
    local = report({"title": marked, "raw_citation": ENTRY.replace(TITLE, marked)})
    online = report({**FOUND, "title": "A made-up title on the porting of patches: 100\\% & more_"})
    findings = run(tmp_path, cache, FakeHallucinator(local, online), monkeypatch)
    assert by_check(findings, "references.summary")[0].message.endswith(
        "1 found, 0 not found, 0 with other authors or identifiers, 0 not looked up")


def test_lookups_that_failed_at_side_sources_leave_the_warning(tmp_path, cache, monkeypatch):
    online = report({"status": "inconclusive", "failed_dbs": ["PubMed", "ACL Anthology"],
                     "db_results": [{"db": "CrossRef", "status": "no_match"}, {"db": "PubMed", "status": "error"},
                                    {"db": "ACL Anthology", "status": "timeout"}]})
    findings = run(tmp_path, cache, FakeHallucinator(report({}), online), monkeypatch)
    assert by_check(findings, "references.not-found")[0].message.endswith(
        "was not found in DBLP, CrossRef, DataCite, OpenAlex")


def test_reference_whose_lookup_failed_at_crossref_gets_a_note_and_no_warning(tmp_path, cache, monkeypatch):
    failed = report({"status": "inconclusive", "failed_dbs": ["CrossRef"],
                     "db_results": [{"db": "CrossRef", "status": "error"}, {"db": "PubMed", "status": "no_match"}]})
    findings = run(tmp_path, cache, FakeHallucinator(report({}), failed), monkeypatch)
    [note] = by_check(findings, "references.unchecked")
    assert note.severity is Severity.INFO
    assert note.message == ("Reference [1] was not looked up, since the lookup failed at CrossRef. A later run repeats "
                            "the lookup")
    assert not by_check(findings, "references.not-found")
    assert by_check(findings, "references.summary")[0].message.endswith("0 found, 0 not found, 0 with other authors or "
                                                                        "identifiers, 1 not looked up")


def test_online_run_that_fails_is_reported_and_leaves_its_references_unchecked(tmp_path, cache, monkeypatch):
    fake = FakeHallucinator(report({}), named={"online": OSError("made-up failure")})
    findings = run(tmp_path, cache, fake, monkeypatch)
    [error] = by_check(findings, "references.error")
    assert error.message == "The online lookups did not finish: made-up failure"
    assert by_check(findings, "references.unchecked")[0].message.startswith(
        "Reference [1] was not looked up, since the lookup failed at CrossRef.")
    assert not by_check(findings, "references.not-found")


def test_online_run_that_fails_is_reported_only_for_the_papers_with_references_in_it(tmp_path, cache, monkeypatch):
    fake = FakeHallucinator(named={"paper-1": report({}), "paper-2": report({"status": "verified"}),
                                   "online": OSError("made-up failure")})
    monkeypatch.setattr(references.subprocess, "run", fake)
    papers = [Paper(paper_id=number, pdf=tmp_path / f"{number}.pdf") for number in (1, 2)]
    findings = references.check_batch(papers, profile_with(cache), tmp_path / "work")
    assert len(by_check(findings[1], "references.error")) == 1 and not by_check(findings[2], "references.error")


def test_online_run_that_fails_is_not_reported_for_a_paper_whose_lookup_failed_only_at_the_registry_of_a_doi(
        tmp_path, cache, monkeypatch, indexes):
    indexes.down = {"crossref_dois"}
    indexes.agencies[DOI.lower()] = "Crossref"
    fake = FakeHallucinator(named={"paper-1": report({}), "paper-2": report(TECH_REPORT),
                                   "online": OSError("made-up failure")})
    monkeypatch.setattr(references.subprocess, "run", fake)
    papers = [Paper(paper_id=number, pdf=tmp_path / f"{number}.pdf") for number in (1, 2)]
    findings = references.check_batch(papers, profile_with(cache), tmp_path / "work")
    assert len(by_check(findings[1], "references.error")) == 1 and not by_check(findings[2], "references.error")
    assert by_check(findings[2], "references.unchecked")[0].message.startswith(
        "Reference [1] was not looked up, since the lookup failed at CrossRef.")


def test_batch_looks_up_the_open_references_of_all_papers_in_one_online_run(tmp_path, cache, monkeypatch):
    second = "A second made-up title on the porting of patches"
    online = report({"status": "verified", "source": "CrossRef", "db_results": [{"db": "CrossRef", "status": "match"}]},
                    {"title": second, "db_results": [{"db": "CrossRef", "status": "no_match"}]})
    fake = FakeHallucinator(named={"paper-1": report({}), "paper-2": report({"status": "verified"}, {"title": second}),
                                   "online": online})
    monkeypatch.setattr(references.subprocess, "run", fake)
    papers = [Paper(paper_id=number, pdf=tmp_path / f"{number}.pdf") for number in (1, 2)]
    findings = references.check_batch(papers, profile_with(cache), tmp_path / "work")
    assert len(fake.calls) == 3
    assert (tmp_path / "work" / "references" / "online.bib").read_text(encoding="utf-8").count("@misc") == 2
    assert not by_check(findings[1], "references.not-found")
    [missing] = by_check(findings[2], "references.not-found")
    assert missing.message.startswith(f'Reference [2] "{second}" was not found in DBLP, CrossRef')


def test_batch_names_on_stderr_how_many_references_the_online_sources_get(tmp_path, cache, monkeypatch, capsys):
    fake = FakeHallucinator(named={"paper-1": report({}), "paper-2": report({"status": "verified"}, {}, {})})
    monkeypatch.setattr(references.subprocess, "run", fake)
    papers = [Paper(paper_id=number, pdf=tmp_path / f"{number}.pdf") for number in (1, 2)]
    references.check_batch(papers, profile_with(cache), tmp_path / "work")
    assert capsys.readouterr().err == "Asking the online sources about 3 of 4 references.\n"


@pytest.mark.parametrize(("entry", "options"), [({"status": "verified"}, {}), ({}, {"online": False})])
def test_batch_that_asks_no_online_source_names_none_on_stderr(tmp_path, cache, monkeypatch, capsys, entry, options):
    run(tmp_path, cache, FakeHallucinator(report(entry)), monkeypatch, **options)
    assert capsys.readouterr().err == ""


def test_paper_whose_local_run_fails_gets_an_error_while_the_other_papers_are_checked(tmp_path, cache, monkeypatch):
    fake = FakeHallucinator(named={"paper-1": OSError("made-up failure"), "paper-2": report({"status": "verified"})})
    monkeypatch.setattr(references.subprocess, "run", fake)
    papers = [Paper(paper_id=number, pdf=tmp_path / f"{number}.pdf") for number in (1, 2)]
    findings = references.check_batch(papers, profile_with(cache), tmp_path / "work")
    assert [f.message for f in findings[1]] == ["The reference check did not run: made-up failure"]
    assert by_check(findings[2], "references.summary")[0].message.startswith("1 reference checked")


def test_offline_arxiv_database_joins_the_local_lookups(tmp_path, cache, monkeypatch):
    arxiv_db = tmp_path / "arxiv.db"
    arxiv_db.write_text("", encoding="utf-8")
    fake = FakeHallucinator("offline-run.json")
    run(tmp_path, cache, fake, monkeypatch, online=False, arxiv_db=str(arxiv_db))
    command = fake.calls[0][0]
    assert command[command.index("--arxiv-offline") + 1] == str(arxiv_db)
    assert "arXiv" not in fake.disabled()


def test_local_corpus_of_the_template_joins_the_local_run_alone(tmp_path, cache, monkeypatch):
    fake = FakeHallucinator(report({}))
    run(tmp_path, cache, fake, monkeypatch, local_corpus=str(tmp_path / "corpus"))
    local, online = fake.calls[0][0], fake.calls[1][0]
    assert local[local.index("--local-corpus") + 1] == str(tmp_path / "corpus")
    assert "--local-corpus" not in online


def test_run_without_a_local_corpus_in_the_template_names_none(tmp_path, cache, monkeypatch):
    fake = FakeHallucinator(report({"status": "verified"}))
    run(tmp_path, cache, fake, monkeypatch)
    assert "--local-corpus" not in fake.calls[0][0]


def test_parse_report_finds_dois_in_the_reference_text():
    entry = {"original_number": 4, "title": "T", "status": "verified",
             "raw_citation": "A. B, “T,” 2020, doi: 10.1000/abc(1)), see https://doi.org/10.2000/X.Y."}
    [ref] = references.parse_report([{"references": [entry]}])
    assert ref.dois == ("10.1000/abc(1)", "10.2000/X.Y")


@pytest.mark.parametrize("wrapped", ["10.1109/ ASWEC.2008.4483193", "10.1109/ASWEC.2008. 4483193"])
def test_doi_cut_by_a_line_break_still_finds_the_retraction_notice(tmp_path, cache, monkeypatch, wrapped):
    # Hallucinator turns the line break inside a wrapped DOI into a space.
    cut = json.loads((FIXTURES / "offline-run.json").read_text(encoding="utf-8"))
    entry = next(r for r in cut[0]["references"] if r["original_number"] == 10)
    entry["raw_citation"] = entry["raw_citation"].replace("10.1109/ASWEC.2008.4483193", wrapped)
    findings = run(tmp_path, cache, FakeHallucinator(cut), monkeypatch)
    [retracted] = by_check(findings, "references.retracted")
    assert retracted.evidence.startswith("DOI 10.1109/aswec.2008.4483193.")


@pytest.mark.parametrize(("doi", "notice"), [
    ("10.9999/sample.1", None), ("10.9999/sample.2", None), ("10.9999/sample.3", "Retraction of 2022-06-01")])
def test_only_a_retraction_or_a_concern_that_is_in_force_is_reported(tmp_path, cache, monkeypatch, doi, notice):
    entry = {"status": "verified", "raw_citation": f"{ENTRY[:-1]}, doi: {doi}."}
    findings = run(tmp_path, cache, FakeHallucinator(report(entry)), monkeypatch, online=False)
    found = [finding.message.split(" notice: ")[1] for finding in by_check(findings, "references.retracted")]
    assert found == ([notice] if notice else [])


def test_note_names_three_references_with_a_comma_before_the_last(tmp_path, cache, monkeypatch):
    findings = run(tmp_path, cache, FakeHallucinator(report(BOOK, BOOK, BOOK)), monkeypatch, online=False)
    assert by_check(findings, "references.unconfirmed")[0].message.startswith(
        "References [1], [2], and [3] were not found, as is")


def test_author_mismatch_names_the_first_four_authors_of_a_record(tmp_path, cache, monkeypatch):
    names = ["Petra Zeller", "Hana Novak", "Carla Marsh", "Dele Okafor", "Erik Lindqvist"]
    findings = run(tmp_path, cache, FakeHallucinator(report({**OTHER_AUTHORS, "found_authors": names})), monkeypatch,
                   online=False)
    assert by_check(findings, "references.author-mismatch")[0].message.endswith(
        "whose authors differ: Petra Zeller, Hana Novak, Carla Marsh, Dele Okafor et al.")


def test_finding_names_a_reference_by_at_most_90_characters_of_its_title(tmp_path, cache, monkeypatch):
    findings = run(tmp_path, cache, FakeHallucinator(report({"title": f"{TITLE} {TITLE} {TITLE}"})), monkeypatch,
                   online=False)
    assert by_check(findings, "references.not-found")[0].message == (
        f'Reference [1] "{TITLE} {TITLE} A m..." was not found in DBLP')


def test_doi_followed_by_a_comma_is_read_without_the_comma():
    assert set(references._dois("in Proc. ICSE, doi: 10.1145/3377811.3380362, 2020.")) == {"10.1145/3377811.3380362"}


def test_doi_followed_by_a_year_is_read_without_the_year():
    assert "10.1145/3377811.3380362" in references._dois("ICSE, 2020, doi: 10.1145/3377811.3380362. 2020.")


@pytest.mark.parametrize(("venue", "arxiv_id"), [
    ("arXiv preprint arXiv: 2401.01234v2", "2401.01234v2"),
    ("arXiv e-prints, p. arXiv:2101.00001, 2021", "2101.00001"),
    ("CoRR, vol. abs/2101.00001, 2021", "2101.00001"),
    ("CoRR abs/2101.00001 (2021)", "2101.00001"),
    ("arXiv preprint arXiv:2101. 00001, 2021", "2101.00001"),
    ("CoRR, vol. abs/1207. 7214, 2012", "1207.7214"),
    ("2021. https://arxiv.org/abs/2101.00001", "2101.00001"),
    ("2021. https://arxiv.org/pdf/2101.00001v3", "2101.00001v3"),
    ("2006, arXiv:cs/0601001", "cs/0601001"),
    ("CoRR, vol. abs/hep-th/9901001, 1999", "hep-th/9901001"),
    ("2006, arXiv:cs.SE/0601001v2", "cs/0601001v2"),
    ("arXiv preprint, 2021. https://www.example.org/labs/2101.00001", ""),
    ("arXiv preprint, 2021, pp. 2101. 00001", ""),
    ("Made-up Review, 2021. https://www.example.io/0601001", "")])
def test_parse_report_finds_an_arxiv_id_in_the_forms_of_common_styles(venue, arxiv_id):
    assert parsed(raw_citation=f"A. Quill, “{TITLE},” {venue}.").arxiv_id == arxiv_id


def test_missing_binary_is_reported_as_an_error(tmp_path, cache, monkeypatch):
    (cache / "hallucinator" / reference_setup.VERSION / "hallucinator-cli").unlink()
    [error] = run(tmp_path, cache, FakeHallucinator("offline-run.json"), monkeypatch)
    assert error.check == "references.error" and error.severity is Severity.WARNING
    assert "Hallucinator is not installed" in error.message and "peercheck --setup" in error.message


def test_missing_dblp_database_is_reported_as_an_error(tmp_path, cache, monkeypatch):
    (cache / "hallucinator" / "dblp.db").unlink()
    [error] = run(tmp_path, cache, FakeHallucinator("offline-run.json"), monkeypatch)
    assert error.check == "references.error" and "offline DBLP database is missing" in error.message


def test_broken_pdf_is_reported_with_the_message_of_the_tool(tmp_path, cache, monkeypatch):
    stderr = (FIXTURES / "broken-pdf.stderr").read_text(encoding="utf-8")
    [error] = run(tmp_path, cache, FakeHallucinator(returncode=1, stderr=stderr), monkeypatch)
    assert error.check == "references.error"
    assert error.message.endswith("Error: PDF extraction error: backend error: failed to open PDF: MuPDF error, "
                                  "code: 7, message: no objects found")


@pytest.mark.parametrize("stderr", [
    "Error: DBLP database has no schema version. Please rebuild with 'hallucinator-tui update-dblp'.",
    "Error: Query returned no rows"])
def test_empty_or_old_offline_database_is_reported_with_the_command_that_rebuilds_it(tmp_path, cache, monkeypatch,
                                                                                    stderr):
    [error] = run(tmp_path, cache, FakeHallucinator(returncode=1, stderr=stderr), monkeypatch, online=False)
    assert error.message == ("The reference check did not run: an offline database of Hallucinator is empty or out "
                             "of date; run peercheck --setup --refresh")


@pytest.mark.parametrize("written", ["broken-pdf.stderr", {"references": 3}, [3], [{"references": 3}],
                                     [{"references": [{"db_results": [3]}]}]])
def test_report_that_is_no_json_or_has_another_form_is_reported_as_an_error(tmp_path, cache, monkeypatch, written):
    findings = run(tmp_path, cache, FakeHallucinator(written), monkeypatch, online=False)
    assert [finding.check for finding in findings] == ["references.error"]
    assert findings[0].message.startswith("The reference check did not run: ")


def test_report_of_an_earlier_run_is_not_read_when_a_run_writes_none(tmp_path, cache, monkeypatch):
    run(tmp_path, cache, FakeHallucinator("offline-run.json"), monkeypatch, online=False)
    findings = run(tmp_path, cache, FakeHallucinator(), monkeypatch, online=False)
    assert [finding.message for finding in findings] == ["No reference list was found in the PDF"]


def test_run_gets_an_empty_configuration_file_in_place_of_the_settings_of_the_user(tmp_path, cache, monkeypatch):
    fake = FakeHallucinator("offline-run.json")
    run(tmp_path, cache, fake, monkeypatch, online=False)
    command = fake.calls[0][0]
    assert Path(command[command.index("--config") + 1]).read_text(encoding="utf-8") == ""


def test_run_that_exceeds_the_timeout_is_reported_as_an_error(tmp_path, cache, monkeypatch):
    def slow(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    [error] = run(tmp_path, cache, slow, monkeypatch, timeout=5)
    assert error.check == "references.error" and "within 5 seconds" in error.message


def test_pdf_without_references_is_reported_as_an_error(tmp_path, cache, monkeypatch):
    [error] = run(tmp_path, cache, FakeHallucinator(), monkeypatch)
    assert (error.check, error.message) == ("references.error", "No reference list was found in the PDF")


def test_missing_retraction_data_is_reported_beside_the_lookup_findings(tmp_path, cache, monkeypatch):
    (cache / "retraction_watch.csv").unlink()
    findings = run(tmp_path, cache, FakeHallucinator("offline-run.json"), monkeypatch, online=False)
    [error] = by_check(findings, "references.error")
    assert "Retraction Watch data is missing" in error.message
    assert len(by_check(findings, "references.not-found")) == 2


def test_cache_defaults_to_the_peercheck_cache_folder(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.setattr(reference_setup.platform, "system", lambda: "Linux")
    settings = references.settings_from({})
    assert settings.binary == tmp_path / "peercheck" / "hallucinator" / reference_setup.VERSION / "hallucinator-cli"
    assert settings.offline == {"DBLP": tmp_path / "peercheck" / "hallucinator" / "dblp.db"}
    assert settings.retraction_csv == tmp_path / "peercheck" / "retraction_watch.csv"

"""Tests of the dblp index on a tiny dump that uses the entities of dblp.dtd."""

from __future__ import annotations

import gzip
import shutil
from pathlib import Path

import pytest

from peercheck import dblp
from peercheck.models import Person

FIXTURES = Path(__file__).parent / "fixtures" / "dblp"
DUMP = FIXTURES / "dblp.xml"


def build(*people: Person, dump: Path = DUMP, dtd: Path | None = None) -> dblp.DblpIndex:
    return dblp.build_index(dump, people, dtd)


def keys(index: dblp.DblpIndex, person: Person, since: int | None = None) -> list[str]:
    return [p.key for p in index.publications_of(person, since)]


class TestNames:
    def test_fold_removes_accents_case_and_punctuation(self):
        assert dblp.fold("Jürgen Müller-Lüdenscheidt") == "jurgen muller ludenscheidt"
        assert dblp.fold("Søren Groß") == "soren gross"

    def test_base_name_removes_the_homonym_suffix(self):
        assert dblp.base_name("Ana Pérez 0002") == "Ana Pérez"
        assert dblp.base_name("Robin X. Okafor") == "Robin X. Okafor"

    def test_loose_key_keeps_first_and_last_word(self):
        assert dblp.loose_key("Robin X. Okafor") == dblp.loose_key("Robin Okafor") == "robin okafor"

    @pytest.mark.parametrize("text", [
        "22/2001", "homepages/22/2001", "pid/22/2001", "https://dblp.org/pid/22/2001.html",
        "https://dblp.uni-trier.de/pid/22/2001.xml", "dblp.org/pid/22/2001/",
    ])
    def test_parse_pid_reads_ids_keys_and_urls(self, text):
        assert dblp.parse_pid(text) == "22/2001"

    def test_parse_pid_keeps_dashes_and_name_ids(self):
        assert dblp.parse_pid("https://dblp.org/pid/52/2402-2.html") == "52/2402-2"
        assert dblp.parse_pid("https://dblp.org/pid/z/AndreasZeller.html") == "z/AndreasZeller"

    def test_parse_pid_rejects_other_text(self):
        assert dblp.parse_pid("https://dblp.org/pers/hd/z/Zeller:Andreas") == ""
        assert dblp.parse_pid("https://example.org/pid/x") == ""
        assert dblp.parse_pid("") == ""


class TestScan:
    def test_entities_of_the_dtd_resolve_in_names(self):
        index = build(Person("Jürgen", "Müller"))
        identity = index.identity(Person("Jürgen", "Müller"))
        assert identity.names == ("Jürgen Müller",)
        assert identity.method == "name"

    def test_gzip_dump_reads_with_a_dtd_elsewhere(self, tmp_path):
        dump = tmp_path / "dump" / "dblp.xml.gz"
        dump.parent.mkdir()
        with DUMP.open("rb") as source, gzip.open(dump, "wb") as target:
            shutil.copyfileobj(source, target)
        index = build(Person("Jürgen", "Müller"), dump=dump, dtd=FIXTURES / "dblp.dtd")
        assert keys(index, Person("Jürgen", "Müller")) == [
            "conf/icse/Brandt25", "conf/icse/MullerO24", "journals/tse/PerezM20",
        ]

    def test_missing_dtd_raises_a_clear_error(self, tmp_path):
        dump = tmp_path / "dblp.xml"
        shutil.copy(DUMP, dump)
        with pytest.raises(FileNotFoundError, match="dblp.dtd"):
            build(Person("Jürgen", "Müller"), dump=dump)

    def test_external_entities_other_than_the_dtd_read_as_empty(self, tmp_path):
        (tmp_path / "secret.txt").write_text("SECRET")
        shutil.copy(FIXTURES / "dblp.dtd", tmp_path / "dblp.dtd")
        (tmp_path / "dblp.xml").write_text(
            '<?xml version="1.0" encoding="ISO-8859-1"?>\n'
            '<!DOCTYPE dblp SYSTEM "dblp.dtd" [<!ENTITY leak SYSTEM "secret.txt">]>\n'
            '<dblp><article key="journals/x/A20"><author>J&uuml;rgen M&uuml;ller</author>'
            "<title>Leak &leak; here.</title><year>2020</year></article>"
            '<www key="homepages/11/1001"><author>J&uuml;rgen M&uuml;ller</author></www></dblp>\n'
        )
        index = build(Person("Jürgen", "Müller"), dump=tmp_path / "dblp.xml")
        assert [p.title for p in index.publications.values()] == ["Leak here"]

    def test_publication_fields_drop_markup_and_final_period(self):
        index = build(Person("Jürgen", "Müller"))
        publication = index.publications["conf/icse/MullerO24"]
        assert publication.title == "Flaky Tests in Synthetic Projects"
        assert publication.year == 2024
        assert publication.doi == "10.1145/1111111.1111112"
        assert publication.authors == ("Jürgen Müller", "Robin X. Okafor")

    def test_editors_do_not_count_as_authors(self):
        index = build(Person("Jürgen", "Müller"))
        assert "conf/icse/2024" not in keys(index, Person("Jürgen", "Müller"))

    def test_arxiv_link_gives_the_arxiv_doi(self):
        index = build(Person("Ana", "Pérez", dblp="22/2002"))
        assert index.publications["journals/corr/abs-2401-01234"].doi == "10.48550/arxiv.2401.01234"

    def test_index_keeps_only_publications_of_the_people(self):
        index = build(Person("Jürgen", "Müller"))
        assert "conf/msr/Other25" not in index.publications

    def test_plain_names_need_one_scan(self, monkeypatch):
        runs = []
        original = dblp._Scan.run
        monkeypatch.setattr(dblp._Scan, "run", lambda self, *args: runs.append(1) or original(self, *args))
        build(Person("Jürgen", "Müller"), Person("Robin", "Okafor"))
        assert len(runs) == 1


class TestIdentity:
    def test_pid_selects_the_names_of_its_record_only(self):
        person = Person("Ana", "Pérez", dblp="https://dblp.org/pid/22/2001.html")
        index = build(person)
        identity = index.identity(person)
        assert (identity.names, identity.method, identity.ambiguous) == (("Ana Pérez 0001",), "pid", False)
        assert keys(index, person) == ["journals/tse/PerezM20"]

    def test_homonyms_without_affiliation_stay_ambiguous(self):
        person = Person("Ana", "Pérez")
        identity = build(person).identity(person)
        assert identity.ambiguous
        assert identity.records == 3
        assert set(identity.names) == {"Ana Pérez", "Ana Pérez 0001", "Ana Pérez 0002"}

    def test_affiliation_resolves_a_homonym(self):
        person = Person("Ana", "Perez", affiliation="Universidad de Ejemplo")
        identity = build(person).identity(person)
        assert (identity.names, identity.pid, identity.method) == (("Ana Pérez 0001",), "22/2001", "name and affiliation")

    def test_middle_name_matches_by_first_and_last_name(self):
        person = Person("Robin", "Okafor")
        index = build(person)
        assert index.identity(person).method == "first and last name"
        assert keys(index, person) == ["conf/icse/MullerO24"]

    def test_exact_and_middle_name_records_together_are_ambiguous(self):
        person = Person("Lena", "Brandt")
        index = build(person)
        identity = index.identity(person)
        assert (identity.ambiguous, identity.records, identity.method) == (True, 2, "ambiguous name")
        assert keys(index, person) == ["conf/icse/Brandt25", "journals/corr/abs-2601-00001"]

    def test_affiliation_picks_one_of_the_name_forms(self):
        person = Person("Lena", "Brandt", affiliation="Synthetic University of Delft")
        identity = build(person).identity(person)
        assert (identity.names, identity.method) == (("Lena Q. Brandt",), "name and affiliation")

    def test_alias_with_another_first_name_runs_a_second_scan(self, monkeypatch):
        runs = []
        original = dblp._Scan.run
        monkeypatch.setattr(dblp._Scan, "run", lambda self, *args: runs.append(1) or original(self, *args))
        person = Person("François", "Lemaître")
        index = build(person)
        assert keys(index, person) == ["conf/sigsoft/Lemaitre23", "journals/corr/abs-2401-01234"]
        assert len(runs) == 2

    def test_merged_record_follows_its_crossref_to_an_earlier_target(self):
        person = Person("Kimberly", "Doe", dblp="99/9999")
        index = build(person)
        assert index.identity(person).names == ("Kim Doe",)
        assert keys(index, person) == ["conf/sigsoft/Lemaitre23"]

    def test_unknown_pid_reports_pid_not_found(self):
        person = Person("Nobody", "Here", dblp="12/34")
        identity = build(person).identity(person)
        assert (identity.names, identity.method) == ((), "pid not found")

    def test_unknown_name_has_no_match(self):
        person = Person("Nobody", "Here")
        assert build(person).identity(person) == dblp.Identity()

    def test_lookup_without_affiliation_finds_the_only_input_of_that_name(self):
        index = build(Person("Jürgen", "Müller", affiliation="University of Testville"))
        assert index.identity(Person("Jurgen", "Muller")).names == ("Jürgen Müller",)


class TestIndex:
    def test_publications_of_filters_by_year(self):
        person = Person("Jürgen", "Müller")
        assert keys(build(person), person, since=2021) == ["conf/icse/Brandt25", "conf/icse/MullerO24"]

    def test_find_doi_ignores_case(self):
        index = build(Person("Jürgen", "Müller"))
        assert index.find_doi("10.1109/tse.2020.0000001").key == "journals/tse/PerezM20"
        assert index.find_doi("10.9999/none") is None

    def test_save_and_load_keep_the_index(self, tmp_path):
        people = (Person("Jürgen", "Müller"), Person("Ana", "Pérez"))
        index = build(*people)
        index.save(tmp_path / "index.json.gz")
        loaded = dblp.load_index(tmp_path / "index.json.gz")
        assert loaded.publications == index.publications
        assert loaded.identities == index.identities
        assert keys(loaded, people[1]) == keys(index, people[1])

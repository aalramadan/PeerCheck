"""Tests of the dblp index on a tiny dump that uses the entities of dblp.dtd."""

from __future__ import annotations

import gzip
import json
import re
import shutil
from pathlib import Path

import pytest
from lxml import etree

from peercheck import dblp
from peercheck.models import Person

FIXTURES = Path(__file__).parent / "fixtures" / "dblp"
DUMP = FIXTURES / "dblp.xml"


def build(*people: Person, dump: Path = DUMP, dtd: Path | None = None) -> dblp.DblpIndex:
    return dblp.build_index(dump, people, dtd)


def keys(index: dblp.DblpIndex, person: Person, since: int | None = None) -> list[str]:
    return [p.key for p in index.publications_of(person, since)]


def write_dump(folder: Path, records: str, encoding: str = "ISO-8859-1", subset: str = "") -> Path:
    """Write a dump of the given records beside a copy of the DTD and return its path."""
    shutil.copy(FIXTURES / "dblp.dtd", folder / "dblp.dtd")
    (folder / "dblp.xml").write_text(
        f'<?xml version="1.0" encoding="{encoding}"?>\n<!DOCTYPE dblp SYSTEM "dblp.dtd"{subset}>\n'
        f"<dblp>{records}</dblp>\n",
        encoding=encoding,
    )
    return folder / "dblp.xml"


def homonyms(folder: Path, note: str) -> Path:
    """Write a dump with two records of Wei Zhang, the first with an affiliation note, and return its path."""
    return write_dump(
        folder,
        f'<www key="homepages/10/0001"><author>Wei Zhang 0001</author><note type="affiliation">{note}</note></www>'
        '<www key="homepages/10/0002"><author>Wei Zhang 0002</author></www>',
    )


def count_reads(monkeypatch) -> list[str]:
    """Record each read of the dump by its kind, people or publications."""
    reads = []
    for kind in ("read_people", "read_publications"):
        original = getattr(dblp._Scan, kind)
        monkeypatch.setattr(dblp._Scan, kind, lambda self, *args, kind=kind, original=original: (
            reads.append(kind) or original(self, *args)))
    return reads


def parsed_keys(monkeypatch) -> list[str]:
    """Record the key of each publication record that lxml parses."""
    parsed = []
    original = dblp._Scan._publication
    monkeypatch.setattr(
        dblp._Scan, "_publication",
        lambda self, element, names: parsed.append(element.get("key")) or original(self, element, names),
    )
    return parsed


class TestNames:
    def test_fold_removes_accents_case_and_punctuation(self):
        assert dblp.fold("Jürgen Müller-Lüdenscheidt") == "jurgen muller ludenscheidt"
        assert dblp.fold("Søren Groß") == "soren gross"

    def test_fold_parts_words_at_dashes_and_quotes_outside_ascii(self):
        assert dblp.fold("University of Wisconsin–Madison") == "university of wisconsin madison"
        assert dblp.fold("King’s College") == dblp.fold("King's College") == "king s college"

    def test_base_name_removes_the_homonym_suffix(self):
        assert dblp.base_name("Ana Pérez 0002") == "Ana Pérez"
        assert dblp.base_name("Robin X. Okafor") == "Robin X. Okafor"

    def test_loose_keys_keep_first_and_last_word(self):
        assert dblp.loose_keys("Robin X. Okafor") == dblp.loose_keys("Robin Okafor") == ("robin okafor",)

    @pytest.mark.parametrize("ascii_name, name", [
        ("Juergen Mueller", "Jürgen Müller"), ("Jurgen Mueller", "Jürgen Müller"), ("Jurgen Muller", "Jürgen Müller"),
        ("Soeren Gross", "Søren Groß"), ("Aase Haugen", "Åse Haugen"),
    ])
    def test_loose_keys_hold_the_ascii_spellings_of_umlauts(self, ascii_name, name):
        assert set(dblp.loose_keys(ascii_name)) <= set(dblp.loose_keys(name))

    @pytest.mark.parametrize("one, other", [
        ("Lei Quellxue", "Lei Quellxu"), ("Yue Quellmar", "Yu Quellmar"), ("Jae Quellmar", "Ja Quellmar"),
        ("Joe Roe", "Jo Ro"), ("Aaron Baar", "Aron Bar"), ("Juergen Mueller", "Jurgen Muller"),
    ])
    def test_loose_keys_keep_two_plain_names_apart(self, one, other):
        assert not set(dblp.loose_keys(one)) & set(dblp.loose_keys(other))

    def test_loose_keys_ignore_a_generational_suffix(self):
        assert dblp.loose_keys("Guy L. Steele Jr.") == dblp.loose_keys("Guy Steele") == ("guy steele",)
        assert dblp.loose_keys("Kim Doe III") == dblp.loose_keys("Kim Doe")

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

    def test_names_need_one_read_of_the_people_and_one_of_the_publications(self, monkeypatch):
        reads = count_reads(monkeypatch)
        build(Person("Jürgen", "Müller"), Person("Robin", "Okafor"))
        assert reads == ["read_people", "read_publications"]


MULLER = Person("Jürgen", "Müller")
# The person record writes the name in a form of its own, so that it selects no publication by its bytes.
WWW = '<www key="homepages/11/1001"><author>J&#252;rgen M&#252;ller</author></www>'
OTHER = ('<article key="journals/x/B21"><author>Unrelated Person</author><title>Other.</title><year>2021</year>'
         '</article>')


def article(author: str) -> str:
    return f'<article key="journals/x/A20">{author}<title>Kept.</title><year>2020</year></article>'


class TestSelectedRecords:
    def test_lxml_parses_only_the_records_of_the_people(self, monkeypatch):
        parsed = parsed_keys(monkeypatch)
        build(MULLER)
        assert {"conf/icse/MullerO24", "journals/tse/PerezM20", "conf/icse/Brandt25"} <= set(parsed)
        assert not {"conf/msr/Other25", "conf/kbse/Perez22", "journals/corr/abs-2401-01234"} & set(parsed)

    def test_selection_finds_what_a_parse_of_the_whole_dump_finds(self, monkeypatch):
        people = [MULLER, Person("Ana", "Pérez"), Person("François", "Lemaître"),
                  Person("Kimberly", "Doe", dblp="99/9999"), Person("Lena", "Brandt"), Person("Robin", "Okafor"),
                  Person("Søren", "Groß")]
        selected = build(*people)
        monkeypatch.setattr(dblp, "_ROOT", re.compile(rb"no root, so the dump passes whole"))
        whole = build(*people)
        assert (selected.publications, selected.identities) == (whole.publications, whole.identities)

    def test_records_cut_at_the_end_of_a_chunk_are_found(self, monkeypatch):
        people = [MULLER, Person("Ana", "Pérez"), Person("François", "Lemaître"), Person("Lena", "Brandt")]
        whole = build(*people)
        monkeypatch.setattr(dblp, "_CHUNK", 64)
        assert build(*people) == whole

    def test_record_longer_than_a_chunk_leaves_the_records_after_it_selected(self, tmp_path, monkeypatch):
        long = f'<article key="journals/x/L19"><author>Unrelated Person</author><title>{"Long " * 60}</title></article>'
        dump = write_dump(tmp_path, long + OTHER + article("<author>J&uuml;rgen M&uuml;ller</author>") + WWW)
        monkeypatch.setattr(dblp, "_CHUNK", 256)
        parsed = parsed_keys(monkeypatch)
        build(MULLER, dump=dump)
        assert parsed == ["journals/x/A20"]

    @pytest.mark.parametrize("author", [
        "<author>J&#252;rgen M&#xFC;ller</author>",
        "<author>\n  J&uuml;rgen M&uuml;ller\n</author>",
        "<author>Jürgen Müller</author>",
        "<author><![CDATA[Jürgen Müller]]></author>",
        """<author orcid='0000-0000-0000-0002' label="a > b" >J&uuml;rgen M&uuml;ller</author >""",
        '<author größe="1">J&uuml;rgen M&uuml;ller</author>',
        "<author>Unrelated Person</author><author>J&uuml;rgen M&uuml;ller</author>",
    ])
    def test_author_written_in_another_form_is_found(self, tmp_path, author):
        index = build(MULLER, dump=write_dump(tmp_path, OTHER + article(author) + WWW))
        assert list(index.publications) == ["journals/x/A20"]

    @pytest.mark.parametrize("markup", [
        "<!-- a comment that holds </article> -->",
        "<?instruction </article> ?>",
    ])
    def test_end_tag_inside_a_comment_or_an_instruction_ends_no_record(self, tmp_path, markup):
        author = f"{markup}<author>J&uuml;rgen M&uuml;ller</author>"
        index = build(MULLER, dump=write_dump(tmp_path, OTHER + article(author) + WWW))
        assert list(index.publications) == ["journals/x/A20"]

    def test_name_in_the_bytes_of_another_encoding_is_found(self, tmp_path):
        records = OTHER + article("<author>Jürgen Müller</author>") + WWW
        index = build(MULLER, dump=write_dump(tmp_path, records, encoding="UTF-8"))
        assert list(index.publications) == ["journals/x/A20"]

    def test_entity_that_the_dump_itself_defines_anew_resolves_in_a_name(self, tmp_path):
        records = OTHER + article("<author>J&ouml;rgen M&ouml;ller</author>") + WWW
        index = build(MULLER, dump=write_dump(tmp_path, records, subset=' [<!ENTITY ouml "&#252;">]'))
        assert list(index.publications) == ["journals/x/A20"]

    @pytest.mark.parametrize("name", [
        "S&#xF8;ren Unrelated", "Unrelated &amp; &lt;Person&gt; &apos;A&apos; &quot;B&quot;"])
    def test_hex_reference_or_xml_entity_in_another_name_leaves_its_record_out(self, tmp_path, monkeypatch, name):
        other = OTHER.replace("Unrelated Person", name)
        dump = write_dump(tmp_path, other + article("<author>J&uuml;rgen M&uuml;ller</author>") + WWW)
        parsed = parsed_keys(monkeypatch)
        build(MULLER, dump=dump)
        assert parsed == ["journals/x/A20"]

    def test_entity_of_the_dtd_that_holds_markup_leaves_the_name_to_lxml(self, tmp_path):
        dump = write_dump(tmp_path, OTHER + article("<author>J&uuml;rgen M&uuml;ller&mark;</author>") + WWW)
        with (tmp_path / "dblp.dtd").open("a", encoding="ascii") as handle:
            handle.write('<!ENTITY mark "<sup>1</sup>">\n')
        assert list(build(MULLER, dump=dump).publications) == ["journals/x/A20"]

    @pytest.mark.parametrize("reference", ["&nosuchname;", "&#xZZ;", "&#99999999999;"])
    def test_reference_of_no_known_character_fails_as_in_a_parse_of_the_whole_dump(self, tmp_path, reference):
        records = OTHER + article(f"<author>Unrelated{reference} Person</author>") + WWW
        with pytest.raises(etree.XMLSyntaxError):
            build(MULLER, dump=write_dump(tmp_path, records))


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

    @pytest.mark.parametrize("affiliation, note", [
        ("ETH", "Delft University of Technology, The Netherlands"),
        ("Lund", "Lundbeck A/S, Copenhagen, Denmark"),
    ])
    def test_affiliation_inside_a_word_of_a_note_leaves_homonyms_ambiguous(self, tmp_path, affiliation, note):
        person = Person("Wei", "Zhang", affiliation=affiliation)
        assert build(person, dump=homonyms(tmp_path, note)).identity(person).ambiguous

    def test_affiliation_of_three_letters_picks_no_homonym(self, tmp_path):
        person = Person("Wei", "Zhang", affiliation="UW")
        assert build(person, dump=homonyms(tmp_path, "UW Madison, USA")).identity(person).ambiguous

    def test_ascii_spelling_of_umlauts_finds_the_dblp_name(self):
        person = Person("Juergen", "Mueller")
        assert build(person).identity(person).names == ("Jürgen Müller",)

    @pytest.mark.parametrize("first, last, held", [
        ("Lei", "Quellxue", "Lei Quellxu"), ("Yue", "Quellmar", "Yu Quellmar")])
    def test_plain_name_that_ends_in_ue_does_not_find_the_name_without_the_e(self, tmp_path, first, last, held):
        dump = write_dump(tmp_path, f'<www key="homepages/12/0001"><author>{held}</author></www>')
        assert build(Person(first, last), dump=dump).identity(Person(first, last)) == dblp.Identity()

    @pytest.mark.parametrize("first, last, held", [
        ("Joerg", "Quellmar", "Jorg Quellmar"), ("Jorg", "Quellmar", "Joerg Quellmar"),
        ("Tavi", "Quellmueller", "Tavi Quellmuller"), ("Aase", "Quellmar", "Ase Quellmar"),
        ("Tavi", "Quellmaer", "Tavi Quellmar"),
    ])
    def test_plain_spelling_of_an_umlaut_finds_the_other_plain_spelling_where_no_record_holds_its_own(
            self, tmp_path, first, last, held):
        dump = write_dump(tmp_path, f'<www key="homepages/12/0001"><author>{held}</author></www>')
        identity = build(Person(first, last), dump=dump).identity(Person(first, last))
        assert (identity.names, identity.method) == ((held,), "first and last name")

    def test_record_under_the_spelling_of_a_plain_name_keeps_the_other_spelling_out(self, tmp_path):
        dump = write_dump(
            tmp_path,
            '<www key="homepages/12/0001"><author>Joerg Quellmar</author></www>'
            '<www key="homepages/12/0002"><author>Jorg Quellmar</author></www>',
        )
        people = [Person("Joerg", "Quellmar"), Person("Jorg", "Quellmar")]
        index = build(*people, dump=dump)
        assert [index.identity(person).names for person in people] == [("Joerg Quellmar",), ("Jorg Quellmar",)]

    def test_another_middle_name_is_another_person(self, tmp_path):
        dump = write_dump(
            tmp_path,
            '<www key="homepages/13/0001"><author>Mona Reza Farid</author></www>'
            '<www key="homepages/13/0002"><author>Mona Amin Farid</author></www>',
        )
        people = [Person("Mona Reza", "Farid"), Person("Mona R.", "Farid"), Person("Mona A. K.", "Farid"),
                  Person("Mona", "Farid")]
        index = build(*people, dump=dump)
        assert [index.identity(person).names for person in people] == [
            ("Mona Reza Farid",), ("Mona Reza Farid",), ("Mona Amin Farid",), ("Mona Reza Farid", "Mona Amin Farid"),
        ]

    def test_alias_of_a_record_excuses_no_other_middle_name(self, tmp_path):
        people = "<author>Mona Amin Farid</author><author>Mona Quellmar</author>"
        dump = write_dump(tmp_path, f'<www key="homepages/13/0002">{people}</www>')
        assert build(Person("Mona Reza", "Farid"), dump=dump).identity(Person("Mona Reza", "Farid")) == dblp.Identity()

    def test_alias_with_another_first_name_needs_no_further_read(self, monkeypatch):
        reads = count_reads(monkeypatch)
        person = Person("François", "Lemaître")
        index = build(person)
        assert keys(index, person) == ["conf/sigsoft/Lemaitre23", "journals/corr/abs-2401-01234"]
        assert reads == ["read_people", "read_publications"]

    def test_merged_record_follows_its_crossref_to_an_earlier_target(self, monkeypatch):
        reads = count_reads(monkeypatch)
        person = Person("Kimberly", "Doe", dblp="99/9999")
        index = build(person)
        assert index.identity(person).names == ("Kim Doe",)
        assert keys(index, person) == ["conf/sigsoft/Lemaitre23"]
        assert reads == ["read_people", "read_people", "read_publications"]

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

    def test_missing_lists_the_people_the_index_was_not_built_for(self):
        index = build(Person("Jürgen", "Müller"))
        assert index.missing([Person("Jürgen", "Müller"), Person("Lena", "Brandt")]) == [Person("Lena", "Brandt")]

    def test_index_of_the_first_version_loads_and_counts_everyone_as_missing(self, tmp_path):
        person = Person("Jürgen", "Müller")
        data = {"version": 1, "source": "dblp.xml", "publications": [],
                "names": {"jurgen muller": ["name:jurgen muller|"]},
                "identities": {"name:jurgen muller|": [["Jürgen Müller"], "11/1001", 1, False, "name"]}}
        with gzip.open(tmp_path / "index.json.gz", "wt", encoding="utf-8") as handle:
            json.dump(data, handle)
        loaded = dblp.load_index(tmp_path / "index.json.gz")
        assert loaded.identity(person).names == ("Jürgen Müller",)
        assert loaded.missing([person]) == [person]

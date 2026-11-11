"""Tests of the conflict check on synthetic people and the tiny dblp dump."""

from __future__ import annotations

from pathlib import Path

import pytest

from peercheck import cli, conflicts, dblp
from peercheck.models import Person

DUMP = Path(__file__).parent / "fixtures" / "dblp" / "dblp.xml"
MULLER = Person("Jürgen", "Müller", "j.mueller@testville.example", "University of Testville")
OKAFOR = Person("Robin", "Okafor", "robin@riverside.example", "Riverside Research Lab")
PEREZ = Person("Ana", "Pérez", "ana@ejemplo.example", "Universidad de Ejemplo")
GROSS = Person("Søren", "Groß", "soren@gmail.com", "Independent")
UNRELATED = Person("Unrelated", "Person", "u@nowhere.example", "Nowhere Institute")
KIM = Person("Kim", "Doe", "kim.doe@cs.testville.example", "Testville University")
LEMAITRE = Person("François", "Lemaître", "f.lemaitre@ejemplo.example", "Example Labs Inc.")
BRANDT = Person("Lena", "Brandt", "lena@delft.example", "Synthetic University of Delft")
PAT = Person("Pat", "Webmail", "pat@gmail.com", "")
PC_MULLER = Person("Jürgen", "Müller", "J.Mueller@testville.example", "University of Testville")
AUTHORS = {1: [MULLER, OKAFOR], 2: [PEREZ, GROSS], 3: [UNRELATED]}
COMMITTEE = [KIM, LEMAITRE, BRANDT, PAT, PC_MULLER]
OPTIONS = {"reference_year": 2026}


@pytest.fixture(scope="module")
def index() -> dblp.DblpIndex:
    people = [person for group in AUTHORS.values() for person in group] + COMMITTEE + [Person("Lena", "Brandt")]
    return dblp.build_index(DUMP, people)


@pytest.fixture(scope="module")
def found(index) -> dict[tuple[int, str], conflicts.Conflict]:
    result = conflicts.find_conflicts(AUTHORS, COMMITTEE, index, options=OPTIONS)
    return {(c.paper_id, c.member.name): c for c in result}


class TestAffiliations:
    @pytest.mark.parametrize("first, second, words", [
        ("University of Manchester", "The University of Manchester, UK", "manchester"),
        ("TU Delft", "Delft University of Technology, The Netherlands", "delft"),
        ("Stanford University", "Stanford University, CA, USA", "stanford university"),
        ("Univeristy of Stutgart", "University of Stuttgart", "stutgart"),
        ("Microsoft Research", "Microsoft", "microsoft"),
        ("Example Labs; University of Testville", "Testville University", "testville"),
    ])
    def test_affiliations_of_one_organization_match(self, first, second, words):
        assert conflicts.affiliation_match(first, second) == words

    @pytest.mark.parametrize("first, second", [
        ("University of California, Berkeley", "University of California, Los Angeles"),
        ("Universidad de Ejemplo, Spain", "Universitat Politecnica, Spain"),
        ("", "University of Testville"),
    ])
    def test_affiliations_of_different_organizations_do_not_match(self, first, second):
        assert conflicts.affiliation_match(first, second) == ""

    @pytest.mark.parametrize("first, second, words", [
        ("CMU", "Carnegie Mellon University", "cmu (carnegie mellon)"),
        ("Massachusetts Institute of Technology", "MIT", "massachusetts (mit)"),
        ("TU Darmstadt", "Technische Universität Darmstadt", "darmstadt tu (technische universitat)"),
        ("UIUC", "University of Illinois at Urbana-Champaign", "uiuc (university illinois urbana champaign)"),
        ("UIUC", "University of Illinois Urbana–Champaign", "uiuc (university illinois urbana champaign)"),
        ("University of Pennsylvania", "UPenn", "pennsylvania (upenn)"),
        ("UW", "University of Washington", "uw (university washington)"),
        ("Chinese University of Hong Kong", "CUHK", "kong (cuhk)"),
        ("CUHK", "Chinese University of Hong Kong", "cuhk (chinese university hong kong)"),
    ])
    def test_abbreviations_match_through_the_alternates_of_hotcrp(self, first, second, words):
        assert conflicts.affiliation_match(first, second) == words

    @pytest.mark.parametrize("first, second", [
        ("Arizona State University", "University of Arizona"),
        ("York University", "New York University"),
        ("The Chinese University of Hong Kong", "The University of Hong Kong"),
        ("Hong Kong Polytechnic University", "The University of Hong Kong"),
        ("Washington University in St. Louis", "University of Washington"),
        ("Michigan State University", "University of Michigan"),
        ("Columbia University", "University of British Columbia"),
        ("Pennsylvania State University", "University of Pennsylvania"),
        ("University of Chicago", "University of Illinois Chicago"),
        ("Boston College", "Boston University"),
        ("UW Madison", "University of Washington"),
        ("UIUC", "University of Illinois Chicago"),
    ])
    def test_sync_words_of_hotcrp_keep_organizations_of_one_name_apart(self, first, second):
        assert conflicts.affiliation_match(first, second) == ""

    @pytest.mark.parametrize("first, second", [
        ("Technical University of Munich", "University of Munich"),
        ("Toronto Metropolitan University", "University of Toronto"),
        ("Politecnico di Milano", "Università degli Studi di Milano"),
    ])
    def test_a_shared_city_word_never_joins_institutions_of_different_kinds(self, first, second):
        assert conflicts.affiliation_match(first, second) == ""

    @pytest.mark.parametrize("first, second, words", [
        ("University of Toronto", "Univ. of Toronto, Canada", "toronto"),
        ("Technical University of Munich", "TU Munich", "munich"),
    ])
    def test_one_institution_written_two_ways_still_matches(self, first, second, words):
        assert conflicts.affiliation_match(first, second) == words

    @pytest.mark.parametrize("first, second", [
        ("Universty of Toronto", "Stanford University"),
        ("German Aerospace Center", "Technical University of Munich, Germany"),
        ("Karolinska Institutet", "Massachusetts Institute of Technology"),
        ("Dipartimento di Informatica, Università di Pisa", "School of Informatics, University of Edinburgh"),
    ])
    def test_a_strong_word_never_matches_a_weak_word_by_spelling(self, first, second):
        assert conflicts.affiliation_match(first, second) == ""

    @pytest.mark.parametrize("first, second", [
        ("Independent Researcher", "Independent Researcher"),
        ("N/A", "N/A"),
        ("No affiliation", "No affiliation"),
        ("Universidad Politécnica de Madrid", "Universitat Politècnica de Catalunya"),
        ("Università degli Studi di Milano", "Università degli Studi di Napoli Federico II"),
        ("Lunds universitet", "Uppsala universitet"),
        ("Pontifícia Universidade Católica do Rio de Janeiro", "Pontifícia Universidade Católica do Rio Grande do Sul"),
        ("Universidad Nacional de Colombia", "Universidad Nacional Autónoma de México"),
        ("Department of Electrical and Computer Engineering, University of Waterloo",
         "Department of Electrical Engineering, Stanford University"),
        ("Data Science Institute, Imperial College London", "Center for Data Science, New York University"),
    ])
    def test_placeholders_and_generic_words_make_no_match(self, first, second):
        assert conflicts.affiliation_match(first, second) == ""


class TestDomains:
    @pytest.mark.parametrize("email, domain", [
        ("a@cs.ox.ac.uk", "ox.ac.uk"), ("b@mail.tsinghua.edu.cn", "tsinghua.edu.cn"), ("c@cs.ubc.ca", "ubc.ca"),
        ("d@gmail.com", "gmail.com"), ("e@US.IBM.com", "ibm.com"),
    ])
    def test_org_domain_keeps_the_registered_name(self, email, domain):
        assert conflicts.org_domain(email) == domain

    @pytest.mark.parametrize("email, domain", [
        ("a@etri.re.kr", "etri.re.kr"), ("b@anssi.gouv.fr", "anssi.gouv.fr"), ("c@inegi.gob.mx", "inegi.gob.mx"),
        ("d@smith.me.uk", "smith.me.uk"), ("e@gns.cri.nz", "gns.cri.nz"), ("f@a.b.test.ck", "b.test.ck"),
        ("g@www.www.ck", "www.ck"), ("h@ac.uk", ""),
    ])
    def test_org_domain_keeps_one_label_below_the_public_suffix(self, email, domain):
        assert conflicts.org_domain(email) == domain

    def test_webmail_domains_of_any_country_never_make_a_conflict(self):
        authors = {1: [Person("A", "One", "a@yahoo.co.uk")]}
        assert conflicts.find_conflicts(authors, [Person("B", "Two", "b@yahoo.co.uk")], options=OPTIONS) == []

    @pytest.mark.parametrize("domain", ["mail.com", "seznam.cz", "wp.pl", "uol.com.br", "tuta.io", "189.cn"])
    def test_common_webmail_providers_never_make_a_conflict(self, domain):
        authors = {1: [Person("A", "One", f"a@{domain}")]}
        assert conflicts.find_conflicts(authors, [Person("B", "Two", f"b@{domain}")], options=OPTIONS) == []

    def test_webmail_option_adds_a_domain(self):
        authors = {1: [Person("A", "One", "a@mail.example")]}
        committee = [Person("B", "Two", "b@mail.example")]
        assert len(conflicts.find_conflicts(authors, committee, options=OPTIONS)) == 1
        assert conflicts.find_conflicts(authors, committee, options={**OPTIONS, "webmail": ["mail.example"]}) == []

    def test_webmail_option_takes_a_single_domain(self):
        authors = {1: [Person("A", "One", "a@mail.example")]}
        committee = [Person("B", "Two", "b@mail.example")]
        assert conflicts.find_conflicts(authors, committee, options={**OPTIONS, "webmail": "mail.example"}) == []


class TestFindConflicts:
    def test_conflicts_cover_the_expected_pairs_only(self, found):
        assert sorted(found) == [
            (1, "Jürgen Müller"), (1, "Kim Doe"), (1, "Lena Brandt"), (2, "François Lemaître"),
        ]

    def test_shared_domain_and_affiliation_give_two_reasons(self, found):
        conflict = found[1, "Kim Doe"]
        assert conflict.kinds == ("email domain", "affiliation")
        assert conflict.others == (MULLER,)
        assert conflict.reasons == (
            "Kim Doe and Jürgen Müller share the email domain testville.example",
            "Kim Doe (Testville University) and Jürgen Müller (University of Testville) share the words testville",
        )

    def test_recent_joint_paper_gives_a_coauthor_conflict(self, found):
        conflict = found[1, "Lena Brandt"]
        assert conflict.kinds == ("co-author",)
        assert conflict.reasons == ((
            "Lena Brandt and Jürgen Müller wrote 1 dblp paper together since 2023: "
            "Regression Test Selection for Synthetic Builds (2025, dblp conf/icse/Brandt25)"
        ),)

    def test_pc_member_among_the_authors_is_reported_with_the_other_reasons(self, found):
        conflict = found[1, "Jürgen Müller"]
        assert conflict.kinds == ("author", "co-author")
        assert conflict.reasons[0] == "Jürgen Müller is an author of the paper (same email)"
        assert "Flaky Tests in Synthetic Projects (2024, dblp conf/icse/MullerO24)" in conflict.reasons[1]

    def test_joint_paper_before_the_window_is_no_conflict(self, found):
        assert (2, "Jürgen Müller") not in found

    def test_affiliation_keeps_a_homonym_from_making_a_false_coauthor_conflict(self, found):
        assert found[2, "François Lemaître"].kinds == ("email domain",)

    def test_window_follows_the_options(self, index):
        older = conflicts.find_conflicts({2: [PEREZ]}, [PC_MULLER], index, options={"reference_year": 2022})
        assert [c.kinds for c in older] == [("co-author",)]

    def test_ambiguous_name_asks_for_a_check(self, index):
        found = conflicts.find_conflicts({1: [MULLER]}, [Person("Lena", "Brandt")], index, options=OPTIONS)
        assert found[0].reasons[0].endswith("The name Lena Brandt matches 2 dblp person records; confirm the person")

    def test_people_with_different_dblp_ids_are_not_one_author(self):
        author = Person("Ana", "Pérez", "ana.perez@ejemplo.example", "Universidad de Ejemplo", dblp="22/2001")
        member = Person("Ana", "Pérez", "aperez@labs.example", "Example Labs Inc.", dblp="https://dblp.org/pid/22/2002")
        assert conflicts.find_conflicts({1: [author]}, [member], options=OPTIONS) == []

    def test_one_dblp_person_under_two_name_forms_is_an_author_and_no_coauthor(self):
        author = Person("Robin", "Okafor", "robin.okafor@gmail.com")
        member = Person("Robin X.", "Okafor", "r.okafor@riverside.example")
        index = dblp.build_index(DUMP, [author, member])
        found = conflicts.find_conflicts({1: [author]}, [member], index, options=OPTIONS)
        assert [(c.kinds, c.reasons) for c in found] == [
            (("author",), ("Robin X. Okafor is an author of the paper (same dblp person ID)",)),
        ]

    def test_people_listed_twice_give_one_row_with_one_set_of_reasons(self):
        author = Person("Robin", "Okafor", "robin@riverside.example", "Riverside Research Lab")
        member = Person("Ana", "Ruiz", "ana@riverside.example", "Riverside Research Lab")
        found = conflicts.find_conflicts({1: [author, author]}, [member, member], options=OPTIONS)
        assert [(c.others, c.kinds, len(c.reasons)) for c in found] == [((author,), ("email domain", "affiliation"), 2)]


class TestRows:
    def test_rows_hold_the_columns_of_a_sheet(self, found):
        row = conflicts.rows([found[1, "Kim Doe"]])[0]
        assert tuple(row) == conflicts.COLUMNS
        assert (row["Paper"], row["PC member"], row["With"], row["Kinds"]) == (
            "1", "Kim Doe", "Jürgen Müller", "email domain; affiliation",
        )
        assert row["Reasons"].count("\n") == 1


class TestCommand:
    @pytest.fixture
    def command(self, tmp_path) -> list[str]:
        (tmp_path / "authors.csv").write_text(
            "paper,first,last,email,affiliation\n1,Robin,Okafor,robin@riverside.example,Riverside Research Lab\n",
            encoding="utf-8")
        (tmp_path / "pc.csv").write_text(
            "first,last,email,affiliation\nJürgen,Müller,j.mueller@testville.example,University of Testville\n",
            encoding="utf-8")
        return ["conflicts", "--authors", str(tmp_path / "authors.csv"), "--pc", str(tmp_path / "pc.csv"),
                "--out", str(tmp_path / "conflicts.xlsx")]

    def test_committee_list_is_required(self, command):
        with pytest.raises(SystemExit):
            cli.main([part for part in command if part not in command[command.index("--pc"):command.index("--pc") + 2]])

    def test_years_zero_reaches_the_check(self, command, monkeypatch):
        options = []
        monkeypatch.setattr(conflicts, "find_conflicts", lambda *args: options.append(args[-1]) or [])
        assert cli.main([*command, "--years", "0"]) == 0
        assert options[0]["coauthor_years"] == 0

    def test_save_index_without_a_dump_is_refused(self, command, tmp_path, capsys):
        assert cli.main([*command, "--save-index", str(tmp_path / "index.json.gz")]) == 2
        assert "--dblp-dump" in capsys.readouterr().err
        assert not (tmp_path / "index.json.gz").exists()

    def test_saved_index_that_lacks_a_listed_person_is_refused(self, command, tmp_path, capsys):
        okafor = Person("Robin", "Okafor", "robin@riverside.example", "Riverside Research Lab")
        dblp.build_index(DUMP, [MULLER, okafor]).save(tmp_path / "full.json.gz")
        assert cli.main([*command, "--dblp-index", str(tmp_path / "full.json.gz")]) == 0
        dblp.build_index(DUMP, [MULLER]).save(tmp_path / "partial.json.gz")
        assert cli.main([*command, "--dblp-index", str(tmp_path / "partial.json.gz")]) == 2
        assert "Robin Okafor" in capsys.readouterr().err

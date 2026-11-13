"""Tests of the conflict check on synthetic people and the tiny dblp dump."""

from __future__ import annotations

import gzip
import re
import shutil
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
ADVISOR_OPTIONS = {**OPTIONS, "advisor_papers": 3}


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

    @pytest.mark.parametrize("first, second", [
        ("Northgate Normal University", "Eastfield Normal University"),
        ("Vrije Universiteit Northgate", "Vrije Universiteit Eastfield"),
        ("Hogeschool Northgate", "Hogeschool van Eastfield"),
        ("Northgate University, State Key Laboratory of Software",
         "Eastfield University, State Key Laboratory of Networks"),
        ("Northgate University, School of Big Data", "Eastfield University, Center for Big Data"),
        ("Northgate University of Posts and Telecommunications",
         "Eastfield University of Posts and Telecommunications"),
        ("Northgate University, Laboratory of Image Processing", "Eastfield University, Signal Processing Group"),
        ("Northgate University, School of Communication", "Eastfield University, Communication Networks Group"),
        ("Northgate Communications", "Eastfield University, Communications Laboratory"),
        ("Northgate University, School of Telecommunication", "Eastfield University, Telecommunication Networks Group"),
        ("Northgate Innovation", "Eastfield University, Innovation Center"),
        ("Northgate University, Laboratory of Space Information", "Eastfield Space Center"),
    ])
    def test_a_word_that_many_institutions_share_never_joins_institutions_of_different_names(self, first, second):
        assert conflicts.affiliation_match(first, second) == ""

    @pytest.mark.parametrize("first, second, words", [
        ("Northgate Normal University", "Northgate Normal Univ., School of Computing, Eastfield", "normal northgate"),
        ("East China Normal University, School of Music", "East China Normal University, Department of Astronomy",
         "normal"),
        ("Northgate University, Key Laboratory of Networks", "Key Laboratory of Networks, Northgate University",
         "key northgate"),
        ("University of Hong Kong, Key Laboratory of Networks", "University of Hong Kong, Key Laboratory of Compilers",
         "key"),
        ("Vrije Universiteit", "Vrije Universiteit Northgate", "vrije"),
        ("Shangai Normal University", "Shanghai Normal University, School of Music", "normal"),
        ("East China Normal University II", "East China Normal University Minhang", "normal"),
        ("Central China Normal University / East China Normal University", "East China Normal University Minhang",
         "normal"),
    ])
    def test_such_a_word_still_matches_within_one_institution(self, first, second, words):
        assert conflicts.affiliation_match(first, second) == words

    @pytest.mark.parametrize("first, second, words", [
        ("Key Laboratory of Networks", "Key Lab of Networks", "key"),
        ("Big Data Research Lab", "Big Data Research Laboratory", "big"),
        ("China Mobile Communications Corporation", "China Mobile Communications Corp.", "communications"),
        ("China Telecommunications Corporation", "China Telecommunications Group", "telecommunications"),
        ("Communications Research Centre Canada", "Communications Research Center, Ottawa", "communications"),
        ("National Space Science Center", "National Space Science Centre, Beijing", "space"),
    ])
    def test_such_a_word_still_matches_two_spellings_of_one_organization(self, first, second, words):
        assert conflicts.affiliation_match(first, second) == words

    @pytest.mark.parametrize("word", [
        "Center", "Centre", "Company", "Corp.", "Corporation", "Group", "Lab", "Laboratories", "Laboratory", "Labs",
        "Limited", "Ltd.", "Japan", "Laboratoire",
    ])
    def test_a_unit_a_legal_form_a_country_or_a_generic_word_is_no_name_of_an_institution(self, word):
        assert conflicts.affiliation_match(f"Big Data {word}", "Northgate Big Data") == "big"

    def test_a_weak_word_that_many_institutions_share_parts_no_short_form_from_its_long_form(self):
        words = conflicts.affiliation_match("Penn State University", "Pennsylvania State University")
        assert words == "penn (pennsylvania) state university"

    def test_a_name_joins_two_institutions_that_hold_further_names_of_their_own(self):
        assert conflicts.affiliation_match("Northgate Alpha University", "Northgate Beta University") == "northgate"


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

    @pytest.mark.parametrize("domain", ["ieee.org", "acm.org", "computer.org"])
    def test_member_addresses_of_societies_never_make_a_conflict(self, domain):
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

    def test_blank_emails_do_not_make_two_people_one_author(self):
        found = conflicts.find_conflicts({1: [Person("A", "One", " ")]}, [Person("B", "Two", " ")], options=OPTIONS)
        assert found == []

    def test_people_listed_twice_give_one_row_with_one_set_of_reasons(self):
        author = Person("Robin", "Okafor", "robin@riverside.example", "Riverside Research Lab")
        member = Person("Ana", "Ruiz", "ana@riverside.example", "Riverside Research Lab")
        found = conflicts.find_conflicts({1: [author, author]}, [member, member], options=OPTIONS)
        assert [(c.others, c.kinds, len(c.reasons)) for c in found] == [((author,), ("email domain", "affiliation"), 2)]


def papers_dump(folder: Path, papers: list[tuple[int | None, list[str]]]) -> Path:
    """Write a dblp dump with one person record per author and one article per year and list of authors."""
    people = sorted({author for _, authors in papers for author in authors})
    records = [f'<www key="homepages/{number}"><author>{name}</author><title>Home Page</title></www>'
               for number, name in enumerate(people)]
    records += [f'<article key="journals/x/{number:03}">{"".join(f"<author>{a}</author>" for a in authors)}'
                f"<title>Synthetic Study {number}.</title>{'' if year is None else f'<year>{year}</year>'}</article>"
                for number, (year, authors) in enumerate(papers)]
    shutil.copyfile(DUMP.with_name("dblp.dtd"), folder / "dblp.dtd")
    path = folder / "dblp.xml"
    lines = ['<?xml version="1.0"?>', '<!DOCTYPE dblp SYSTEM "dblp.dtd">', "<dblp>", *records, "</dblp>"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


class TestHomonyms:
    AUTHOR = Person("Tavi", "Quellmar", "tavi@northgate.example")
    COAUTHOR = Person("Ilka", "Varn", "ilka@eastfield.example")
    PELL = Person("Orin", "Pell", "orin@harbor.example")
    MORROW = Person("Dax", "Morrow", "dax@westbrook.example")
    NOTE = "The name Tavi Quellmar matches 2 dblp person records; confirm the person"

    def found(self, folder: Path, papers: list[tuple[int, list[str]]]) -> list[tuple[str, tuple[str, ...], bool]]:
        """Return the member, the kinds, and whether the note stands for each conflict of the two authors."""
        committee = [self.PELL, self.MORROW]
        index = dblp.build_index(papers_dump(folder, papers), [self.AUTHOR, self.COAUTHOR, *committee])
        found = conflicts.find_conflicts({1: [self.AUTHOR, self.COAUTHOR]}, committee, index, options=OPTIONS)
        return [(c.member.name, c.kinds, c.reasons[0].endswith(self.NOTE)) for c in found]

    def test_joint_paper_with_a_coauthor_of_the_submission_leaves_no_person_record_out(self, tmp_path):
        papers = [(2019, ["Tavi Quellmar 0001", "Ilka Varn"]), (2025, ["Tavi Quellmar 0002", "Orin Pell"]),
                  (2025, ["Tavi Quellmar 0001", "Dax Morrow"])]
        assert self.found(tmp_path, papers) == [
            ("Orin Pell", ("co-author",), True), ("Dax Morrow", ("co-author",), True)]

    def test_two_dblp_forms_of_one_name_count_together_beside_a_coauthor_of_the_submission(self, tmp_path):
        papers = [(2024, ["Tavi R. Quellmar", "Orin Pell"]), (2025, ["Tavi Quellmar", "Ilka Varn"])]
        assert self.found(tmp_path, papers) == [("Orin Pell", ("co-author",), True)]


class TestAdvisor:
    SENIOR = Person("Ines", "Varga", "ines@northgate.example")
    JUNIOR = Person("Tomas", "Lind", "tomas@harbor.example")

    def index(self, folder, start=2000, alone=13, joint=3, senior="Ines Varga", more=()) -> dblp.DblpIndex:
        """Return the index of a senior with papers alone from a year on and a junior with four papers from 2010 on."""
        papers = [(start + number, [senior]) for number in range(alone)] + list(more)
        papers += [(2010, ["Tomas Lind", senior])] * joint + [(2011, ["Tomas Lind"])] * (4 - joint)
        return dblp.build_index(papers_dump(folder, papers), [self.SENIOR, self.JUNIOR])

    def test_senior_coauthor_of_the_first_papers_is_a_possible_advisor(self, tmp_path):
        found = conflicts.find_conflicts(
            {1: [self.JUNIOR]}, [self.SENIOR], self.index(tmp_path), options=ADVISOR_OPTIONS)
        assert [(c.kinds, c.reasons) for c in found] == [(("advisor",), ((
            "Ines Varga may have advised Tomas Lind: Ines Varga wrote 3 of the first 4 dblp papers of Tomas Lind, "
            "began publishing 10 years earlier, and has 12 more dblp papers; confirm the relation"
        ),))]

    def test_author_who_may_have_advised_the_member_is_reported_as_well(self, tmp_path):
        found = conflicts.find_conflicts(
            {1: [self.SENIOR]}, [self.JUNIOR], self.index(tmp_path), options=ADVISOR_OPTIONS)
        assert [c.kinds for c in found] == [("advisor",)]
        assert found[0].reasons[0].startswith("Ines Varga may have advised Tomas Lind")

    @pytest.mark.parametrize("change", [{"joint": 2}, {"start": 2006, "alone": 11}, {"alone": 10}])
    def test_fewer_joint_papers_a_later_start_or_too_few_papers_make_no_advisor(self, tmp_path, change):
        index = self.index(tmp_path, **change)
        assert conflicts.find_conflicts({1: [self.JUNIOR]}, [self.SENIOR], index, options=ADVISOR_OPTIONS) == []

    def test_template_without_the_key_reports_no_advisor(self, tmp_path):
        assert conflicts.find_conflicts({1: [self.JUNIOR]}, [self.SENIOR], self.index(tmp_path), options=OPTIONS) == []

    def test_name_of_several_dblp_people_makes_no_advisor(self, tmp_path):
        index = self.index(tmp_path, senior="Ines Varga 0001", more=[(2001, ["Ines Varga 0002"])])
        assert conflicts.find_conflicts({1: [self.JUNIOR]}, [self.SENIOR], index, options=ADVISOR_OPTIONS) == []

    def test_start_of_five_years_earlier_and_ten_papers_more_are_enough(self, tmp_path):
        index = self.index(tmp_path, start=2005, alone=11)
        found = conflicts.find_conflicts({1: [self.JUNIOR]}, [self.SENIOR], index, options=ADVISOR_OPTIONS)
        assert "began publishing 5 years earlier, and has 10 more dblp papers" in found[0].reasons[0]

    def career(self, folder, papers) -> list[conflicts.Conflict]:
        """Return the conflicts of the junior with the senior, who wrote a paper alone each year from 2000 to 2023."""
        papers = papers + [(2000 + number, ["Ines Varga"]) for number in range(24)]
        index = dblp.build_index(papers_dump(folder, papers), [self.SENIOR, self.JUNIOR])
        return conflicts.find_conflicts({1: [self.JUNIOR]}, [self.SENIOR], index, options=ADVISOR_OPTIONS)

    def test_joint_papers_after_the_first_ten_papers_make_no_advisor(self, tmp_path):
        assert self.career(tmp_path, [(2012, ["Tomas Lind", "Ines Varga"])] * 3 + [(2010, ["Tomas Lind"])] * 10) == []

    def test_first_papers_follow_the_years_and_not_the_dblp_keys(self, tmp_path):
        found = self.career(tmp_path, [(2015, ["Tomas Lind"])] * 10 + [(2010, ["Tomas Lind", "Ines Varga"])] * 3)
        assert found[0].reasons[0].startswith(
            "Ines Varga may have advised Tomas Lind: Ines Varga wrote 3 of the first 10")

    def test_person_without_dblp_papers_has_no_advisor_and_advised_no_one(self, tmp_path):
        committee = [Person("Nobody", "Here"), self.SENIOR]
        found = conflicts.find_conflicts({1: [self.JUNIOR]}, committee, self.index(tmp_path), options=ADVISOR_OPTIONS)
        assert [(c.member, c.kinds) for c in found] == [(self.SENIOR, ("advisor",))]

    def test_paper_without_a_year_counts_for_no_rule(self, tmp_path):
        index = self.index(tmp_path, more=[(None, ["Tomas Lind", "Ines Varga"])])
        found = conflicts.find_conflicts({1: [self.JUNIOR]}, [self.SENIOR], index, options=ADVISOR_OPTIONS)
        assert [c.kinds for c in found] == [("advisor",)]
        assert "wrote 3 of the first 4 dblp papers" in found[0].reasons[0]


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
    def command(self, tmp_path, monkeypatch) -> list[str]:
        # An empty cache of its own keeps each run from the DBLP copy of the machine.
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
        (tmp_path / "authors.csv").write_text(
            "paper,first,last,email,affiliation\n1,Robin,Okafor,robin@riverside.example,Riverside Research Lab\n",
            encoding="utf-8")
        (tmp_path / "pc.csv").write_text(
            "first,last,email,affiliation\nJürgen,Müller,j.mueller@testville.example,University of Testville\n",
            encoding="utf-8")
        return ["--conflicts", "--authors", str(tmp_path / "authors.csv"), "--pc", str(tmp_path / "pc.csv"),
                "--out", str(tmp_path / "conflicts.csv")]

    def test_committee_list_is_required(self, command):
        assert cli.main([part for part in command if part not in command[command.index("--pc"):command.index("--pc") + 2]]) == 2

    def test_window_of_the_venue_file_reaches_the_check(self, command, monkeypatch, tmp_path):
        venue = tmp_path / "venue.yaml"
        venue.write_text("name: Test\nsource: https://example.org\nformat:\n  style: IEEE\n  paper_size: [792, 612]\n"
                         "  columns: 2\n  main_pages: 10\n  reference_pages: 2\n"
                         "checks:\n  conflicts:\n    coauthor_years: 0\n", encoding="utf-8")
        options = []
        monkeypatch.setattr(conflicts, "find_conflicts", lambda *args: options.append(args[-1]) or [])
        assert cli.main(["--template", str(venue), *command]) == 0
        assert options[0]["coauthor_years"] == 0

    @staticmethod
    def _setup_dblp(tmp_path) -> tuple[Path, Path]:
        """Place the DBLP fixture where peercheck --setup keeps the dump and its DTD; return the dump and the index."""
        dump, dtd, saved = dblp.files(tmp_path / "cache" / "peercheck")
        dump.parent.mkdir(parents=True)
        dump.write_bytes(gzip.compress(DUMP.read_bytes()))
        shutil.copyfile(DUMP.with_name("dblp.dtd"), dtd)
        return dump, saved

    @staticmethod
    def _dblp_row(tmp_path) -> str:
        page = (tmp_path / "conflicts.html").read_text(encoding="utf-8")
        return re.search(r"DBLP: (used|not used)\.", page).group(1)

    def test_conflict_check_leaves_out_coauthorship_before_setup(self, command, tmp_path, capsys):
        assert cli.main(command) == 0
        assert "peercheck --setup" in capsys.readouterr().err
        assert self._dblp_row(tmp_path) == "not used"

    def test_conflict_check_reads_the_dblp_copy_of_setup_and_saves_the_coauthor_index(self, command, tmp_path):
        _dump, saved = self._setup_dblp(tmp_path)
        assert cli.main(command) == 0
        assert self._dblp_row(tmp_path) == "used"
        assert dblp.load_index(saved).identity(MULLER) is not None

    def test_saved_index_that_holds_every_listed_person_spares_the_scan(self, command, tmp_path, monkeypatch):
        self._setup_dblp(tmp_path)
        assert cli.main(command) == 0
        monkeypatch.setattr(dblp, "build_index", lambda *args: pytest.fail("the saved index covers everyone"))
        assert cli.main(command) == 0
        assert self._dblp_row(tmp_path) == "used"

    def test_saved_index_that_lacks_a_listed_person_is_built_again(self, command, tmp_path):
        _dump, saved = self._setup_dblp(tmp_path)
        dblp.build_index(DUMP, [MULLER]).save(saved)
        okafor = Person("Robin", "Okafor", "robin@riverside.example", "Riverside Research Lab")
        assert dblp.load_index(saved).identity(okafor) is None
        assert cli.main(command) == 0
        assert dblp.load_index(saved).identity(okafor) is not None

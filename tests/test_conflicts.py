"""Tests of the conflict check on synthetic people and the tiny dblp dump."""

from __future__ import annotations

from pathlib import Path

import pytest

from peercheck import conflicts, dblp
from peercheck.inputs import InputError
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
    result = conflicts.find_conflicts(
        AUTHORS, COMMITTEE, index,
        assignments={1: [BRANDT, KIM], 2: [LEMAITRE, PAT], 3: [KIM]},
        declared={1: [KIM], 2: [PC_MULLER], 3: [KIM]},
        options=OPTIONS,
    )
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


class TestDomains:
    @pytest.mark.parametrize("email, domain", [
        ("a@cs.ox.ac.uk", "ox.ac.uk"), ("b@mail.tsinghua.edu.cn", "tsinghua.edu.cn"), ("c@cs.ubc.ca", "ubc.ca"),
        ("d@gmail.com", "gmail.com"), ("e@US.IBM.com", "ibm.com"),
    ])
    def test_org_domain_keeps_the_registered_name(self, email, domain):
        assert conflicts.org_domain(email) == domain

    def test_webmail_domains_of_any_country_never_make_a_conflict(self):
        authors = {1: [Person("A", "One", "a@yahoo.co.uk")]}
        assert conflicts.find_conflicts(authors, [Person("B", "Two", "b@yahoo.co.uk")], options=OPTIONS) == []

    def test_webmail_option_adds_a_domain(self):
        authors = {1: [Person("A", "One", "a@mail.example")]}
        committee = [Person("B", "Two", "b@mail.example")]
        assert len(conflicts.find_conflicts(authors, committee, options=OPTIONS)) == 1
        assert conflicts.find_conflicts(authors, committee, options={**OPTIONS, "webmail": ["mail.example"]}) == []


class TestFindConflicts:
    def test_conflicts_cover_the_expected_pairs_only(self, found):
        assert sorted(found) == [
            (1, "Jürgen Müller"), (1, "Kim Doe"), (1, "Lena Brandt"), (2, "François Lemaître"), (3, "Kim Doe"),
        ]

    def test_shared_domain_and_affiliation_give_two_reasons(self, found):
        conflict = found[1, "Kim Doe"]
        assert conflict.kinds == ("email domain", "affiliation")
        assert conflict.others == (MULLER,)
        assert conflict.reasons == (
            "Kim Doe and Jürgen Müller share the email domain testville.example",
            "Kim Doe (Testville University) and Jürgen Müller (University of Testville) share the words testville",
        )
        assert (conflict.declared, conflict.assigned) == (True, True)

    def test_recent_joint_paper_gives_a_coauthor_conflict(self, found):
        conflict = found[1, "Lena Brandt"]
        assert conflict.kinds == ("co-author",)
        assert conflict.reasons == ((
            "Lena Brandt and Jürgen Müller wrote 1 dblp paper together since 2023: "
            "Regression Test Selection for Synthetic Builds (2025, dblp conf/icse/Brandt25)"
        ),)
        assert (conflict.declared, conflict.assigned) == (False, True)

    def test_pc_member_among_the_authors_is_reported_with_the_other_reasons(self, found):
        conflict = found[1, "Jürgen Müller"]
        assert conflict.kinds == ("author", "co-author")
        assert conflict.reasons[0] == "Jürgen Müller is an author of the paper (same email)"
        assert "Flaky Tests in Synthetic Projects (2024, dblp conf/icse/MullerO24)" in conflict.reasons[1]

    def test_joint_paper_before_the_window_is_no_conflict(self, found):
        assert (2, "Jürgen Müller") not in found

    def test_affiliation_keeps_a_homonym_from_making_a_false_coauthor_conflict(self, found):
        assert found[2, "François Lemaître"].kinds == ("email domain",)

    def test_declared_conflict_without_any_data_is_listed(self, found):
        conflict = found[3, "Kim Doe"]
        assert conflict.kinds == ("declared without support",)
        assert conflict.reasons == ((
            "declared in the conflict export, while no author shares a dblp paper, an email domain, or an "
            "affiliation with Kim Doe"
        ),)

    def test_window_follows_the_options(self, index):
        older = conflicts.find_conflicts({2: [PEREZ]}, [PC_MULLER], index, options={"reference_year": 2022})
        assert [c.kinds for c in older] == [("co-author",)]

    def test_ambiguous_name_asks_for_a_check(self, index):
        found = conflicts.find_conflicts({1: [MULLER]}, [Person("Lena", "Brandt")], index, options=OPTIONS)
        assert found[0].reasons[0].endswith("The name Lena Brandt matches 2 dblp person records; confirm the person")

    def test_without_assignments_or_declarations_the_flags_stay_empty(self, index):
        found = conflicts.find_conflicts({1: [MULLER]}, [KIM], index, options=OPTIONS)
        assert (found[0].declared, found[0].assigned) == (None, None)


class TestReviewerTies:
    def test_assigned_reviewers_who_wrote_together_are_listed(self, index):
        ties = conflicts.reviewer_ties({4: [KIM, LEMAITRE, PAT]}, index, OPTIONS)
        assert [(t.paper_id, t.member.name, t.others[0].name, t.kinds) for t in ties] == [
            (4, "Kim Doe", "François Lemaître", ("reviewer co-authorship",)),
        ]


class TestRows:
    def test_rows_hold_the_columns_of_a_sheet(self, found):
        row = conflicts.rows([found[1, "Kim Doe"]])[0]
        assert tuple(row) == conflicts.COLUMNS
        assert (row["Paper"], row["PC member"], row["With"], row["Kinds"], row["Declared"], row["Assigned"]) == (
            "1", "Kim Doe", "Jürgen Müller", "email domain; affiliation", "yes", "yes",
        )
        assert row["Reasons"].count("\n") == 1


class TestEasyChairFiles:
    def test_members_and_pairs_read_without_header(self, tmp_path):
        (tmp_path / "reviewer.csv").write_text("1,Kim Doe,kim@x.example,PC member\n2,Ana María Pérez,ana@y.example,PC member\n")
        (tmp_path / "assignment.csv").write_text("1,10\n2,10\n2,11\n")
        members = conflicts.read_members(tmp_path / "reviewer.csv")
        assert members[2] == Person("Ana María", "Pérez", "ana@y.example")
        pairs = conflicts.read_pairs(tmp_path / "assignment.csv", members)
        assert {paper: [p.last for p in people] for paper, people in pairs.items()} == {10: ["Doe", "Pérez"], 11: ["Pérez"]}

    def test_header_rows_are_skipped(self, tmp_path):
        (tmp_path / "reviewer.csv").write_text("#,name,email,role\n1,Kim Doe,kim@x.example,PC member\n")
        assert list(conflicts.read_members(tmp_path / "reviewer.csv")) == [1]

    def test_unknown_member_id_raises(self, tmp_path):
        (tmp_path / "conflict.csv").write_text("7,10\n")
        with pytest.raises(InputError, match="PC member 7"):
            conflicts.read_pairs(tmp_path / "conflict.csv", {})

"""Tests of the citation request check on synthetic reviews and the tiny dblp dump."""

from __future__ import annotations

from pathlib import Path

import pytest

from peercheck import dblp
from peercheck.findings import Severity
from peercheck.inputs import read_reviews
from peercheck.models import Person, Review
from peercheck.reviews import citations

FIXTURES = Path(__file__).parent / "fixtures"
MULLER = Person("Jürgen", "Müller", "j.mueller@testville.example")
LEMAITRE = Person("François", "Lemaître", "f.lemaitre@ejemplo.example")
REVIEWERS = [MULLER, LEMAITRE, Person("Kim", "Doe"), Person("Pat", "Reviewer"), Person("Robin", "Okafor")]


@pytest.fixture(scope="module")
def reviews() -> list[Review]:
    return read_reviews(FIXTURES / "reviews")


@pytest.fixture(scope="module")
def index() -> dblp.DblpIndex:
    return dblp.build_index(FIXTURES / "dblp" / "dblp.xml", REVIEWERS + [Person("Ana", "Pérez")])


@pytest.fixture(scope="module")
def found(reviews, index):
    return citations.check_reviews(reviews, {"dblp_index": index})


def checks(findings, check: str):
    return [f for f in findings if f.check == check]


def review(text: str, paper_id: int = 9, reviewer: Person | None = None, review_id: str = "X") -> Review:
    return Review(review_id=review_id, paper_id=paper_id, title="", source="test", author_text=text, reviewer=reviewer)


def one_work_each(*works: tuple[Person, int, str]) -> dblp.DblpIndex:
    """Index one work per person, given as the person, the year, and the title, with the DOI 10.5555/<position>."""
    index = dblp.DblpIndex()
    for number, (person, year, title) in enumerate(works):
        key = f"conf/test/{number}"
        index.publications[key] = dblp.Publication(key, year, title, f"10.5555/{number}", (person.name,))
        index.identities[dblp.person_key(person)] = dblp.Identity((person.name,))
    return index


class TestExtract:
    def test_dois_lose_trailing_punctuation_and_case(self):
        items = citations.extract("See doi:10.1145/3540250.3549115). Also https://doi.org/10.1109/TSE.2020.0000001.")
        assert [i.doi for i in items] == ["10.1145/3540250.3549115", "10.1109/tse.2020.0000001"]

    def test_arxiv_ids_of_both_schemes_become_arxiv_dois(self):
        items = citations.extract("arXiv preprint arXiv:2202.03310v2 and https://arxiv.org/abs/cs/0112017")
        assert [i.doi for i in items] == ["10.48550/arxiv.2202.03310", "10.48550/arxiv.cs/0112017"]

    def test_author_year_citations_keep_surname_and_year(self):
        items = citations.extract("Compare with Zhang et al., 2022, Smith and Doe (2019), and Lee (2021).")
        assert [(i.kind, i.surname, i.year) for i in items] == [
            ("citation", "Zhang", 2022), ("citation", "Smith", 2019), ("citation", "Lee", 2021),
        ]

    def test_years_in_plain_text_are_no_citations(self):
        assert citations.extract("In 2020 the tool changed. Since 2019, May (2021) and ICSE (2020) passed.") == []

    def test_a_reference_entry_with_a_doi_counts_once(self):
        items = citations.extract("[1] Smith, J. and Doe, A. Flaky tests. In Proc. ICSE 2020. doi:10.1145/1.2")
        assert [(i.kind, i.doi) for i in items] == [("doi", "10.1145/1.2")]

    def test_reference_lines_and_quoted_titles_count(self):
        items = citations.extract(
            "Okafor, R. Mining things. MSR 2023.\n"
            "- J. Smith. Test smells in the wild. In Proc. ICSE 2021.\n"
            'The authors should read "Learning to Repair Programs at Scale" first.'
        )
        assert [i.kind for i in items] == ["reference", "reference", "title"]

    def test_a_bulleted_comment_with_a_year_is_no_reference(self):
        assert citations.extract("- In 2020, the authors of the baseline released a second version.") == []

    def test_repeated_items_count_once(self):
        assert len(citations.extract("doi:10.1145/1.2 and again DOI 10.1145/1.2\ndoi:10.1145/1.2")) == 1


class TestRequests:
    def test_review_with_items_gets_an_info_finding_with_count_items_and_phrases(self, found):
        info = checks(found["R1"], "citations.requests")
        assert len(info) == 1
        assert info[0].severity is Severity.INFO
        assert info[0].message == "The review cites 2 works, with the request phrases should also discuss; should cite"
        assert info[0].evidence == "doi: 10.1145/1111111.1111112; citation: Müller et al. (2024)"

    def test_committee_only_fields_stay_out(self, found):
        assert "9999999" not in " ".join(f.evidence for f in found["R1"])

    def test_reviews_without_items_get_no_finding(self, found):
        assert found["R3"] == found["R4"] == found["R6"] == []

    def test_more_works_than_pages_warns(self, found):
        warning = checks(found["R5"], "citations.many-requests")
        assert [w.severity for w in warning] == [Severity.WARNING]
        assert warning[0].message == "The review cites 11 works, more than one per page of a 10-page paper"
        assert "Wren" in warning[0].evidence

    def test_page_count_comes_from_the_options(self, reviews):
        per_paper = citations.check_reviews(reviews, {"pages": {3: 12}})
        assert checks(per_paper["R5"], "citations.many-requests") == []
        assert checks(citations.check_reviews(reviews, {"pages": 11})["R5"], "citations.many-requests") == []


class TestSelfCitation:
    def test_request_for_the_reviewers_own_work_warns(self, found):
        own = checks(found["R1"], "citations.self-citation-request")
        assert len(own) == 1
        assert own[0].severity is Severity.WARNING
        assert own[0].message == "The review asks for 1 work by its own reviewer Jürgen Müller."
        assert "10.1145/1111111.1111112 matches dblp conf/icse/MullerO24 (2024, " in own[0].evidence
        assert "Müller et al. (2024) matches dblp conf/icse/MullerO24" in own[0].evidence
        assert "by first author and year" in own[0].evidence

    def test_count_of_reviews_with_own_requests_covers_all_reviews_of_the_reviewer(self, found):
        own = checks(found["R1"], "citations.self-citation-request")[0]
        assert own.evidence.endswith("this reviewer asks for own works in 1 of 2 reviews")

    def test_request_for_work_of_another_reviewer_of_the_paper_warns(self, found):
        messages = sorted(f.message for f in checks(found["R2"], "citations.self-citation-request"))
        assert messages == [
            "The review asks for 1 work by Jürgen Müller, another reviewer of paper 1.",
            "The review asks for 1 work by its own reviewer François Lemaître.",
        ]

    def test_title_in_a_reference_line_matches(self, found):
        other = next(f for f in checks(found["R2"], "citations.self-citation-request") if "Müller" in f.message)
        assert "matches dblp conf/icse/MullerO24" in other.evidence and other.evidence.endswith("by title")

    def test_arxiv_item_matches_the_arxiv_record_of_an_alias(self, found):
        own = next(f for f in checks(found["R2"], "citations.self-citation-request") if "own" in f.message)
        assert "10.48550/arxiv.2401.01234 matches dblp journals/corr/abs-2401-01234" in own.evidence

    def test_no_index_means_no_self_citation_findings(self, reviews):
        plain = citations.check_reviews(reviews, {})
        assert all(f.check != "citations.self-citation-request" for found in plain.values() for f in found)

    def test_index_option_accepts_the_path_of_a_saved_index(self, reviews, index, tmp_path, found):
        index.save(tmp_path / "index.json.gz")
        assert citations.check_reviews(reviews, {"dblp_index": str(tmp_path / "index.json.gz")}) == found

    def test_ambiguous_reviewer_name_asks_for_a_check(self, index):
        reviewer = Person("Ana", "Pérez")
        found = citations.check_reviews([review("See arXiv:2401.01234.", reviewer=reviewer)], {"dblp_index": index})
        message = checks(found["X"], "citations.self-citation-request")[0].message
        assert message.endswith("The name Ana Pérez matches 3 dblp person records; confirm the person.")

    def test_unrelated_works_give_no_self_citation_finding(self, found):
        assert checks(found["R5"], "citations.self-citation-request") == []

    def test_a_short_quoted_phrase_inside_a_longer_title_asks_for_no_work(self):
        doe = Person("Kim", "Doe")
        index = one_work_each((doe, 2025, "Large Language Models for Automated Program Repair: A Survey."))
        found = citations.check_reviews(
            [review('Section 2 never defines what the paper means by "Large Language Models".', reviewer=doe)],
            {"dblp_index": index},
        )
        assert checks(found["X"], "citations.self-citation-request") == []

    def test_a_quoted_title_with_a_typo_still_matches_by_title(self):
        doe = Person("Kim", "Doe")
        index = one_work_each((doe, 2025, "Large Language Models for Automated Program Repair: A Survey."))
        found = citations.check_reviews(
            [review('Please cite "Large Language Model for Automated Program Repair: A Survey".', reviewer=doe)],
            {"dblp_index": index},
        )
        assert checks(found["X"], "citations.self-citation-request")[0].evidence.endswith(
            "by title; this reviewer asks for own works in 1 of 1 reviews")

    def test_surnames_with_an_apostrophe_or_a_hyphen_match_by_first_author_and_year(self):
        obrien, garcia = Person("Liam", "O'Brien"), Person("Maria", "Garcia-Molina")
        index = one_work_each((obrien, 2024, "Ranking Flaky Test Failures."), (garcia, 2023, "Test Smells in CI."))
        found = citations.check_reviews(
            [review("Please cite O'Brien et al. (2024).", paper_id=1, reviewer=obrien, review_id="A"),
             review("Please also discuss Garcia-Molina et al. (2023).", paper_id=2, reviewer=garcia, review_id="B")],
            {"dblp_index": index},
        )
        assert [f.message for rid in "AB" for f in checks(found[rid], "citations.self-citation-request")] == [
            "The review asks for 1 work by its own reviewer Liam O'Brien.",
            "The review asks for 1 work by its own reviewer Maria Garcia-Molina.",
        ]

    def test_reviewers_named_in_a_non_latin_script_stay_apart(self):
        zhang, li = Person("伟", "张", dblp="11/1111"), Person("娜", "李", dblp="22/2222")
        index = one_work_each((zhang, 2024, "Ranking Flaky Test Failures."), (li, 2023, "Test Smells in CI."))
        found = citations.check_reviews(
            [review("A careful study.", reviewer=zhang, review_id="A"),
             review("Please cite doi:10.5555/1.", reviewer=li, review_id="B")],
            {"dblp_index": index},
        )
        own = checks(found["B"], "citations.self-citation-request")
        assert [f.message for f in own] == ["The review asks for 1 work by its own reviewer 娜 李."]
        assert own[0].evidence.endswith("this reviewer asks for own works in 1 of 1 reviews")

"""Tests of the citation request check on synthetic reviews and the tiny dblp dump."""

from __future__ import annotations

import time
from dataclasses import replace
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
RANKING = "Ranking Flaky Test Failures in Continuous Integration"
REPAIR = "Learning to Repair Programs at Scale"
SMELLS = "Mining Test Smells in the Wild"


@pytest.fixture(scope="module")
def reviews() -> list[Review]:
    return read_reviews(FIXTURES / "reviews" / "reviews.csv")


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


def works(text: str) -> list[tuple[str, str, int | None]]:
    """Return the kind, the surname, and the year of each item of a review text."""
    return [(item.kind, item.surname, item.year) for item in citations.extract(text)]


def second_author(index: dblp.DblpIndex, key: str) -> dblp.DblpIndex:
    """Put the made-up author Alex Smith before the author of one indexed work."""
    work = index.publications[key]
    index.publications[key] = replace(work, authors=("Alex Smith", *work.authors))
    return index


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

    def test_citations_inside_a_bulleted_comment_are_citations_and_no_reference_entry(self):
        items = citations.extract(
            "1. The related work leaves out Okafor et al. (2023) and Lee and Park (2021), which matter here.\n"
            "- Please compare with Smith et al. (2020) on the same projects.")
        assert [(i.kind, i.surname, i.year) for i in items] == [
            ("citation", "Okafor", 2023), ("citation", "Lee", 2021), ("citation", "Smith", 2020),
        ]

    def test_a_reference_entry_that_names_its_authors_as_a_citation_stays_one_reference(self):
        entries = ("[1] Mining Flaky Tests at Scale, Okafor et al. 2023.",
                   "[2] Okafor et al. (2023). Mining flaky tests at scale. In Proc. MSR.",
                   "- Kim Doe and Robin Okafor (2023). Mining flaky tests at scale. Journal of Testing.")
        assert [[i.kind for i in citations.extract(entry)] for entry in entries] == [["reference"]] * 3

    def test_a_quoted_passage_of_the_paper_is_no_title(self):
        items = citations.extract(
            'The row "Baseline + Static Analysis" of the second table is unclear.\n'
            'The caption "Results Are Shown in Figure 3 Top" names no legend.\n'
            'The phrase "(Mean Over Five Runs)" appears twice.\n'
            'The sentence "We Follow Smith et al. in All Experiments" is vague.')
        assert items == []

    def test_a_title_quoted_beside_its_citation_counts_as_one_work(self):
        items = citations.extract(
            'The authors should read Smith et al. (2020), "Learning to Repair Programs at Scale", and '
            '"Mining Test Smells in the Wild" (Lee and Park, 2021) before Rao (2019) on "Ranking Flaky Test Failures".')
        assert [(i.kind, i.text, i.surname, i.year) for i in items] == [
            ("title", "Learning to Repair Programs at Scale", "Smith", 2020),
            ("citation", "Rao (2019)", "Rao", 2019),
            ("title", "Mining Test Smells in the Wild", "Lee", 2021),
            ("title", "Ranking Flaky Test Failures", "", None),
        ]

    def test_citations_in_brackets_and_with_an_ampersand_keep_surname_and_year(self):
        items = citations.extract(
            "Earlier studies (Zhu, 2020; Lee and Park, 2021) and Rao & Sen, 2019 disagree [Kim and Cho 2018].")
        assert sorted((i.kind, i.surname, i.year) for i in items) == [
            ("citation", "Kim", 2018), ("citation", "Lee", 2021), ("citation", "Rao", 2019), ("citation", "Zhu", 2020),
        ]

    def test_a_year_in_brackets_after_another_word_is_no_citation(self):
        assert citations.extract("The run (May, 2021) used the release (Windows 2000) of the venue (ICSE, 2020).") == []

    def test_a_short_month_an_acronym_a_count_or_a_sentence_opener_before_a_year_is_no_citation(self):
        lines = ("The data was collected late (Dec, 2020).",
                 "The survey ran earlier (Sept, 2019).",
                 "The data is old; Indeed, 2015 is long ago for such a corpus.",
                 "This was shown before (NeurIPS, 2019).",
                 "The study covers one system (Linux, 2000 commits) only.",
                 "The last row (Ours, 2023) is not explained.")
        assert [citations.extract(line) for line in lines] == [[]] * len(lines)

    def test_one_author_in_brackets_is_a_citation_before_a_bracket_a_semicolon_or_a_comma(self):
        assert sorted(works("Known since long (MacKay, 1995), as shown (Jun and Lee, 2020; Zhu, 2020a, p. 5).")) == [
            ("citation", "Jun", 2020), ("citation", "MacKay", 1995), ("citation", "Zhu", 2020)]

    def test_a_reference_entry_ends_with_its_citation_or_has_no_word_right_before_it(self):
        entries = ("[1] A study of flaky tests at scale, by Okafor et al. 2023.",
                   "- Mining flaky tests at scale, Okafor et al. (2023), in Proc. MSR.")
        assert [works(entry) for entry in entries] == [[("reference", "", None)]] * 2

    def test_a_reference_entry_with_its_venue_before_a_year_in_brackets_stays_one_reference(self):
        title = RANKING.capitalize()
        entries = (f"[1] K. Doe, {title}, IEEE Transactions on Software Engineering (2025), vol. 3.",
                   f"- K. Doe. {title}. In Proceedings of the Symposium on Software Testing (2025), pp. 1-10.",
                   f"- Doe, K., Okafor, R. {title}. Empir Software Eng (2025) 30:45")
        assert [works(entry) for entry in entries] == [[("reference", "", None)]] * 3

    def test_a_bulleted_comment_with_a_doi_beside_its_citation_counts_one_work(self):
        items = citations.extract("- Please cite the study of Okafor et al. (2023), doi:10.1145/1.2, in Proc. MSR.")
        assert [(i.kind, i.doi) for i in items] == [("doi", "10.1145/1.2")]

    def test_each_title_of_a_list_keeps_the_citation_beside_it(self):
        title_first = f'See "{RANKING}" (Lee et al., 2020), "{REPAIR}" (Rao, 2019), "{SMELLS}" (Park et al., 2021).'
        citation_first = f'See Lee et al. (2020), "{RANKING}", Rao (2019), "{REPAIR}", Park et al. (2021), "{SMELLS}".'
        for text in (title_first, citation_first):
            assert sorted((i.text, i.surname, i.year) for i in citations.extract(text) if i.kind == "title") == [
                (REPAIR, "Rao", 2019), (SMELLS, "Park", 2021), (RANKING, "Lee", 2020)]

    def test_a_title_stands_beside_a_citation_only_without_a_word_and_within_three_characters(self):
        assert works(f'Compare Rao (2019) -- "{RANKING}" -- with Lee (2021) v "{SMELLS}".') == [
            ("citation", "Rao", 2019), ("citation", "Lee", 2021), ("title", "", None), ("title", "", None)]

    def test_a_quoted_title_that_ends_with_its_year_or_its_citation_in_brackets_is_one_title(self):
        items = citations.extract(f'The authors miss "{RANKING} (2025)" and "{SMELLS} (Smith et al., 2024)".')
        assert [(i.kind, i.text, i.surname, i.year) for i in items] == [
            ("title", f"{SMELLS} (Smith et al., 2024)", "Smith", 2024),
            ("title", f"{RANKING} (2025)", "Integration", 2025)]

    def test_a_long_bulleted_line_is_read_within_a_second(self):
        line = "- " + "evaluation " * 10_000 + ", Smith et al. (2020) shows more."
        start = time.perf_counter()
        assert len(citations.extract(line)) == 1
        assert time.perf_counter() - start < 1


class TestRequests:
    def test_review_with_items_gets_an_info_finding_with_count_items_and_phrases(self, found):
        info = checks(found["1A"], "citations.requests")
        assert len(info) == 1
        assert info[0].severity is Severity.INFO
        assert info[0].message == "The review cites 2 works, with the request phrases should also discuss; should cite"
        assert info[0].evidence == "doi: 10.1145/1111111.1111112; citation: Müller et al. (2024)"

    def test_committee_only_fields_stay_out(self, found):
        assert "9999999" not in " ".join(f.evidence for f in found["1A"])

    def test_reviews_without_items_get_no_finding(self, found):
        assert found["2A"] == found["2B"] == found["3B"] == []

    def test_more_works_than_pages_warns(self, found):
        warning = checks(found["3A"], "citations.many-requests")
        assert [w.severity for w in warning] == [Severity.WARNING]
        assert warning[0].message == "The review cites 11 works, more than one per page of a 10-page paper"
        assert "Wren" in warning[0].evidence

    def test_page_count_comes_from_the_options(self, reviews):
        per_paper = citations.check_reviews(reviews, {"pages": {3: 12}})
        assert checks(per_paper["3A"], "citations.many-requests") == []
        assert checks(citations.check_reviews(reviews, {"pages": 11})["3A"], "citations.many-requests") == []


class TestSelfCitation:
    def test_request_for_the_reviewers_own_work_warns(self, found):
        own = checks(found["1A"], "citations.self-citation-request")
        assert len(own) == 1
        assert own[0].severity is Severity.WARNING
        assert own[0].message == "The review asks for 1 work by its own reviewer Jürgen Müller."
        assert "10.1145/1111111.1111112 matches dblp conf/icse/MullerO24 (2024, " in own[0].evidence
        assert "Müller et al. (2024) matches dblp conf/icse/MullerO24" in own[0].evidence
        assert "by first author and year" in own[0].evidence

    def test_count_of_reviews_with_own_requests_covers_all_reviews_of_the_reviewer(self, found):
        own = checks(found["1A"], "citations.self-citation-request")[0]
        assert own.evidence.endswith("this reviewer asks for own works in 1 of 2 reviews")

    def test_request_for_work_of_another_reviewer_of_the_paper_warns(self, found):
        messages = sorted(f.message for f in checks(found["1B"], "citations.self-citation-request"))
        assert messages == [
            "The review asks for 1 work by Jürgen Müller, another reviewer of paper 1.",
            "The review asks for 1 work by its own reviewer François Lemaître.",
        ]

    def test_title_in_a_reference_line_matches(self, found):
        other = next(f for f in checks(found["1B"], "citations.self-citation-request") if "Müller" in f.message)
        assert "matches dblp conf/icse/MullerO24" in other.evidence and other.evidence.endswith("by title")

    def test_arxiv_item_matches_the_arxiv_record_of_an_alias(self, found):
        own = next(f for f in checks(found["1B"], "citations.self-citation-request") if "own" in f.message)
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
        assert checks(found["3A"], "citations.self-citation-request") == []

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

    def test_an_author_year_request_inside_a_bulleted_comment_matches_the_work_of_the_reviewer(self):
        doe = Person("Kim", "Doe")
        index = one_work_each((doe, 2025, "Ranking Flaky Test Failures."))
        found = citations.check_reviews(
            [review("- Please also compare the approach with Doe et al. (2025), which is closer.", reviewer=doe)],
            {"dblp_index": index},
        )
        assert checks(found["X"], "citations.self-citation-request")[0].evidence.startswith(
            "Doe et al. (2025) matches dblp conf/test/0")

    def test_a_title_quoted_beside_its_citation_matches_by_first_author_and_year_or_else_by_title(self):
        doe, okafor = Person("Kim", "Doe"), Person("Robin", "Okafor")
        index = one_work_each((doe, 2025, "Ranking Flaky Failures."), (okafor, 2024, "Mining Test Smells in CI."))
        found = citations.check_reviews(
            [review('Please cite Doe et al. (2025), "Ranking Flaky Tests", and Smith et al. (2024), '
                    '"Mining Test Smells in CI".', reviewer=doe, review_id="A"),
             review("A careful study.", reviewer=okafor, review_id="B")],
            {"dblp_index": index},
        )
        evidence = [f.evidence.split(";")[0] for f in checks(found["A"], "citations.self-citation-request")]
        assert evidence == [
            "Ranking Flaky Tests matches dblp conf/test/0 (2025, Ranking Flaky Failures.) by first author and year",
            "Mining Test Smells in CI matches dblp conf/test/1 (2024, Mining Test Smells in CI.) by title",
        ]

    @pytest.mark.parametrize("text", [
        f'Missing related work: "{RANKING}" (Lee et al., 2020), "{REPAIR}" (Rao et al., 2019).',
        f'Missing related work: "{RANKING}" (Doe, 2024), "{REPAIR}" (Rao, 2019).',
        f"[1] K. Doe, {RANKING.capitalize()}, IEEE Transactions on Software Engineering (2025), vol. 3.",
        f"- Doe, K., Okafor, R. {RANKING.capitalize()}. Empir Software Eng (2025) 30:45",
        f'The authors miss "{RANKING} (2025)" entirely.',
        f'The authors miss "{RANKING} (Lee et al., 2024)" entirely.',
    ], ids=["list-of-titles", "list-with-another-year", "entry-with-venue-and-year", "entry-with-journal-and-year",
            "title-with-year-in-brackets", "title-with-citation-in-brackets"])
    def test_a_title_among_citations_or_before_a_year_in_brackets_matches_the_work_of_the_reviewer_by_title(self, text):
        doe = Person("Kim", "Doe")
        index = one_work_each((doe, 2025, RANKING))
        own = checks(citations.check_reviews([review(text, reviewer=doe)], {"dblp_index": index})["X"],
                     "citations.self-citation-request")
        assert [f.evidence.split(";")[0].split(" matches ")[1] for f in own] == [
            f"dblp conf/test/0 (2025, {RANKING}) by title"]

    def test_a_title_beside_the_citation_of_another_work_keeps_its_own_match(self):
        okafor = Person("Robin", "Okafor")
        index = second_author(one_work_each((okafor, 2024, SMELLS)), "conf/test/0")
        found = citations.check_reviews(
            [review(f'The related work should cover "{SMELLS}" (Smith and Okafor, 2024), "{REPAIR}" (Rao, 2019).',
                    reviewer=okafor)],
            {"dblp_index": index},
        )
        assert checks(found["X"], "citations.self-citation-request")[0].evidence.startswith(
            f"{SMELLS} matches dblp conf/test/0 (2024, {SMELLS}) by first author and year")

    def test_a_title_without_quotes_in_a_bulleted_comment_matches_beside_a_citation_with_another_year_or_author(self):
        doe, okafor = Person("Kim", "Doe"), Person("Robin", "Okafor")
        index = second_author(one_work_each((doe, 2025, RANKING), (okafor, 2024, SMELLS)), "conf/test/1")
        found = citations.check_reviews(
            [review(f"- Please compare with Doe et al. (2024), {RANKING}, which is closer to this work.",
                    paper_id=1, reviewer=doe, review_id="A"),
             review(f"- The authors overlook {SMELLS} by Okafor et al. (2024), which studies the same projects.",
                    paper_id=2, reviewer=okafor, review_id="B")],
            {"dblp_index": index},
        )
        match = f"Doe et al. (2024) matches dblp conf/test/0 (2025, {RANKING}) by title in the same comment"
        assert [f.evidence for f in found["A"]] == [
            "citation: Doe et al. (2024)", f"{match}; this reviewer asks for own works in 1 of 1 reviews"]
        assert checks(found["B"], "citations.self-citation-request")[0].evidence.startswith(
            f"Okafor et al. (2024) matches dblp conf/test/1 (2024, {SMELLS}) by title in the same comment")

    def test_a_citation_repeated_in_a_bulleted_comment_counts_once_and_matches_the_title_spelled_out_there(self):
        doe = Person("Kim", "Doe")
        found = citations.check_reviews(
            [review(f"The approach follows Doe et al. (2024).\n- Please compare with Doe et al. (2024), {RANKING}, "
                    "which is closer to this work.", reviewer=doe)],
            {"dblp_index": one_work_each((doe, 2025, RANKING))},
        )
        assert [f.evidence.split(";")[0] for f in found["X"]] == [
            "citation: Doe et al. (2024)",
            f"Doe et al. (2024) matches dblp conf/test/0 (2025, {RANKING}) by title in the same comment"]

    def test_a_citation_in_plain_text_never_matches_by_title(self):
        doe = Person("Kim", "Doe")
        found = citations.check_reviews(
            [review(f"Please compare with Lee et al. (2024), {RANKING}, which is closer to this work.", reviewer=doe)],
            {"dblp_index": one_work_each((doe, 2025, RANKING))},
        )
        assert checks(found["X"], "citations.self-citation-request") == []

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

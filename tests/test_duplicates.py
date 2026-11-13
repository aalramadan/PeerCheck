"""Tests of the near-duplicate check on synthetic reviews."""

from __future__ import annotations

from pathlib import Path

import pytest

from peercheck.findings import Severity
from peercheck.inputs import read_reviews
from peercheck.models import Person, Review
from peercheck.reviews import duplicates

FIXTURES = Path(__file__).parent / "fixtures" / "reviews"
TEMPLATE = (
    "The paper addresses a relevant and timely problem for the software engineering community, and the "
    "manuscript is generally well written and easy to follow. However, the evaluation is limited and the "
    "threats to validity are not discussed in enough depth."
)


def review(review_id: str, text: str, paper_id: int = 1, reviewer: Person | None = None) -> Review:
    return Review(review_id=review_id, paper_id=paper_id, title="", source="test", author_text=text, reviewer=reviewer)


@pytest.fixture(scope="module")
def fixture_findings():
    return duplicates.check_reviews(read_reviews(FIXTURES / "reviews.csv"), {})


class TestParagraphs:
    def test_blank_lines_separate_paragraphs_and_wrapped_lines_join(self):
        assert duplicates.paragraphs("first line\nwrapped line\n\nsecond") == ["first line wrapped line", "second"]

    def test_list_items_become_paragraphs_of_their_own(self):
        text = "Weaknesses:\n- the first point\n  continues here\n- the second point\n1. a numbered point"
        assert duplicates.paragraphs(text) == [
            "Weaknesses:", "- the first point continues here", "- the second point", "1. a numbered point",
        ]


class TestFixtureReviews:
    def test_every_review_gets_an_entry(self, fixture_findings):
        assert sorted(fixture_findings) == ["1A", "1B", "2A", "2B", "3A", "3B"]

    def test_template_paragraph_flags_each_pair_of_reviews_that_share_it(self, fixture_findings):
        others = {rid: sorted(f.evidence.split(" of review ")[1].split(",")[0] for f in found)
                  for rid, found in fixture_findings.items()}
        assert others == {"1A": ["2A", "2B"], "1B": [], "2A": ["1A", "2B"], "2B": ["1A", "2A"], "3A": [], "3B": []}

    def test_finding_names_the_other_review_paper_reviewer_and_similarity(self, fixture_findings):
        finding = next(f for f in fixture_findings["1A"] if "review 2B" in f.message)
        assert finding.check == "duplicates.near-duplicate"
        assert finding.severity is Severity.WARNING
        assert finding.message == "1 paragraph nearly duplicates text of review 2B on paper 2 by another reviewer"
        assert finding.evidence == "paragraph 2 here and paragraph 1 of review 2B, Jaccard 0.93"

    def test_reuse_by_the_same_reviewer_says_so(self, fixture_findings):
        finding = next(f for f in fixture_findings["2A"] if "review 1A" in f.message)
        assert finding.message.endswith("on paper 1 by the same reviewer")

    def test_short_shared_sentences_stay_below_the_length_cutoff(self, fixture_findings):
        assert fixture_findings["3A"] == fixture_findings["3B"] == []


class TestReviewers:
    def test_reviewers_named_in_a_non_latin_script_are_told_apart_by_their_names(self):
        zhang, li = Person("伟", "张"), Person("娜", "李")
        other = duplicates.check_reviews([review("A", TEMPLATE, reviewer=zhang), review("B", TEMPLATE, 2, li)], {})
        same = duplicates.check_reviews([review("A", TEMPLATE, reviewer=zhang), review("B", TEMPLATE, 2, zhang)], {})
        assert other["A"][0].message.endswith("by another reviewer")
        assert same["A"][0].message.endswith("by the same reviewer")


class TestThresholds:
    def test_paragraphs_of_one_review_are_never_compared(self):
        found = duplicates.check_reviews([review("A", TEMPLATE + "\n\n" + TEMPLATE)], {})
        assert found == {"A": []}

    def test_unrelated_paragraphs_give_no_finding(self):
        other = (
            "The replication package lists the commands for the first research question only, and the scripts "
            "for the second and third questions fail on a clean checkout of the repository."
        )
        assert duplicates.check_reviews([review("A", TEMPLATE), review("B", other, 2)], {}) == {"A": [], "B": []}

    def test_a_higher_threshold_drops_a_moderate_match(self):
        edited = TEMPLATE.replace("generally well written", "mostly clear").replace("enough depth", "detail")
        reviews = [review("A", TEMPLATE), review("B", edited, 2)]
        assert duplicates.check_reviews(reviews, {})["A"]
        assert duplicates.check_reviews(reviews, {"threshold": 0.95}) == {"A": [], "B": []}

    def test_a_pair_just_above_the_threshold_is_found(self):
        edited = (TEMPLATE.replace("addresses", "tackles").replace("generally well written", "mostly clear")
                  .replace("easy to follow", "readable").replace("threats to validity", "limitations"))
        found = duplicates.check_reviews([review("A", TEMPLATE), review("B", edited, 2)], {})
        assert [f.evidence for f in found["A"]] == ["paragraph 1 here and paragraph 1 of review B, Jaccard 0.55"]

    def test_a_paragraph_shared_in_a_non_latin_script_is_found(self):
        russian = ("Статья посвящена актуальной проблеме программной инженерии, и рукопись в целом хорошо написана. "
                   "Однако оценка ограничена, а угрозы валидности обсуждаются недостаточно подробно.")
        found = duplicates.check_reviews([review("A", russian), review("B", russian, 2)], {})
        assert [f.evidence for f in found["A"]] == ["paragraph 1 here and paragraph 1 of review B, Jaccard 1.00"]

    def test_unrelated_paragraphs_in_chinese_never_match(self):
        reviews = [review("A", "本文研究了不稳定测试的检测方法，实验覆盖十二个开源项目。"),
                   review("B", "复现包缺少第二个研究问题的脚本，请补充运行说明。", 2)]
        assert duplicates.check_reviews(reviews, {"min_chars": 0}) == {"A": [], "B": []}

    def test_min_chars_option_lets_short_paragraphs_in(self):
        reviews = [review("A", "Thank you for the opportunity to review this paper."),
                   review("B", "Thank you for the opportunity to review this paper.", 2)]
        assert duplicates.check_reviews(reviews, {})["A"] == []
        assert len(duplicates.check_reviews(reviews, {"min_chars": 20})["A"]) == 1

    def test_several_matching_paragraphs_give_one_finding_per_review_pair(self):
        other = (
            "The replication package lists the commands for the first research question only, and the scripts "
            "for the second and third questions fail on a clean checkout of the repository."
        )
        reviews = [review("A", TEMPLATE + "\n\n" + other), review("B", other + "\n\n" + TEMPLATE, 2)]
        found = duplicates.check_reviews(reviews, {})
        assert len(found["A"]) == len(found["B"]) == 1
        assert found["A"][0].message == "2 paragraphs nearly duplicate text of review B on paper 2"
        assert found["A"][0].evidence == (
            "paragraph 1 here and paragraph 2 of review B, Jaccard 1.00; "
            "paragraph 2 here and paragraph 1 of review B, Jaccard 1.00"
        )

    def test_a_paragraph_inside_a_longer_one_is_found_at_the_ratio_of_their_sizes(self):
        longer = TEMPLATE + " The authors should also release the scripts of the second experiment."
        ratio = len(duplicates._shingles(TEMPLATE, 5)) / len(duplicates._shingles(longer, 5))
        reviews = [review("A", TEMPLATE), review("B", longer, 2)]
        found = duplicates.check_reviews(reviews, {"threshold": ratio})
        assert [f.evidence for f in found["A"]] == [
            f"paragraph 1 here and paragraph 1 of review B, Jaccard {ratio:.2f}"]
        assert duplicates.check_reviews(reviews, {"threshold": ratio + 0.01}) == {"A": [], "B": []}

    def test_invalid_threshold_raises(self):
        with pytest.raises(ValueError, match="threshold"):
            duplicates.check_reviews([review("A", TEMPLATE)], {"threshold": 0})

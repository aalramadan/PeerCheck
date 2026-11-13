"""Tests of the short-review check on made-up reviews."""

from __future__ import annotations

from pathlib import Path

import pytest

from peercheck import profile as profiles
from peercheck.findings import Severity
from peercheck.inputs import read_reviews
from peercheck.models import Review
from peercheck.reviews import short_reviews

FIXTURE = Path(__file__).parent / "fixtures" / "reviews" / "short_reviews.csv"
EXAMPLE_TEMPLATE = Path(__file__).parents[1] / "examples" / "template.yaml"


def review(text: str) -> Review:
    return Review(review_id="X", paper_id=1, title="", source="test", author_text=text)


@pytest.fixture(scope="module")
def found():
    return short_reviews.check_reviews(read_reviews(FIXTURE), {})


def test_a_review_of_one_or_two_sentences_gets_a_note_with_its_sentences(found):
    assert [(f.check, f.severity, f.message) for f in found["21A"]] == [
        ("short_reviews.few-sentences", Severity.INFO, "The review has 2 sentences for the authors"),
    ]


def test_a_review_without_text_for_the_authors_says_so(found):
    assert [f.message for f in found["22A"]] == ["The review has no text for the authors"]


def test_a_review_of_three_sentences_or_three_list_items_gets_no_note(found):
    assert found["21B"] == found["22B"] == []


def test_sentences_in_chinese_are_counted_at_their_full_stops(found):
    assert [f.message for f in found["22C"]] == ["The review has 2 sentences for the authors"]


def test_one_sentence_is_named_in_the_singular():
    assert short_reviews.check_reviews([review("I recommend acceptance")], {})["X"][0].message == (
        "The review has 1 sentence for the authors")


def test_a_period_inside_a_number_ends_no_sentence():
    assert short_reviews.sentences("Version 2.1 of the tool fails on the largest project.") == 1
    assert short_reviews.sentences("The tool fails. The paper is unclear! Is the data public?") == 3


def test_a_full_stop_before_a_closing_quote_or_bracket_ends_a_sentence():
    assert short_reviews.sentences('The authors write "we beat all baselines." This claim is false. Reject.') == 3
    assert short_reviews.sentences("The idea is new (and simple.) The evaluation is thin (one project.) Reject.") == 3


def test_sentences_in_devanagari_are_counted_at_their_dandas():
    text = "यह अस्थिर परीक्षणों का अध्ययन है। प्रयोग पर्याप्त हैं। लेखन स्पष्ट है। स्वीकार करें।"
    assert short_reviews.sentences(text) == 4


def test_min_sentences_option_sets_the_shortest_review_without_a_note():
    reviews = [review("Good paper. Accept.")]
    assert short_reviews.check_reviews(reviews, {"min_sentences": 2}) == {"X": []}
    assert len(short_reviews.check_reviews(reviews, {"min_sentences": 5})["X"]) == 1


def test_the_default_template_holds_the_default_of_min_sentences():
    assert profiles.load(profiles.DEFAULT).options("short_reviews") == short_reviews.DEFAULTS


@pytest.mark.parametrize("template", [*profiles.available(), str(EXAMPLE_TEMPLATE)], ids=lambda name: Path(name).stem)
def test_the_filled_templates_and_the_example_template_turn_the_check_on(template):
    assert profiles.load(template).runs("short_reviews")

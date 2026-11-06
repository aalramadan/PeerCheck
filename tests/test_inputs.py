"""Tests of the readers for PDFs, submission sheets, people lists, and EasyChair review XML."""

import shutil
from pathlib import Path

import pytest

from peercheck import inputs, profile

FIXTURES = Path(__file__).parent / "fixtures"
EASYCHAIR = FIXTURES / "easychair"


def test_pdfs_map_to_ids_and_odd_names_are_reported(tmp_path):
    source = FIXTURES / "papers" / "corrupt.pdf"
    for name in ("CONF_2026_paper_0041.pdf", "CONF_2026_paper_41.pdf", "CONF_2026_paper_0042 (1).pdf",
                 "conf_2026_paper_0043.PDF", "notes.txt"):
        shutil.copy(source, tmp_path / name)
    found = inputs.find_pdfs(tmp_path, profile.load("example-easychair"))
    assert sorted(found.papers) == [41, 43]
    assert found.unmatched == ["CONF_2026_paper_0042 (1).pdf"]
    assert len(found.duplicates) == 1


def test_missing_pdf_folder_is_an_input_error(tmp_path):
    with pytest.raises(inputs.InputError, match="not found"):
        inputs.find_pdfs(tmp_path / "missing", profile.load("example-easychair"))


def test_submission_sheet_gives_titles_by_id():
    titles = inputs.read_submissions(EASYCHAIR / "submissions.csv", profile.load("example-easychair"))
    assert set(titles) == {7, 8}


def test_submission_sheet_without_the_id_column_names_the_column(tmp_path):
    path = tmp_path / "s.csv"
    path.write_text("Number,Title\n1,A\n")
    with pytest.raises(inputs.InputError, match="'#'"):
        inputs.read_submissions(path, profile.load("example-easychair"))


def test_easychair_author_headers_are_understood():
    authors = inputs.read_people(EASYCHAIR / "authors.csv", with_paper=True)
    assert [a.name for a in authors[7]] == ["Maria Lindqvist", "Wei Zhang"]
    assert authors[7][0].affiliation == "KTH Royal Institute of Technology"


def test_people_list_without_names_is_rejected(tmp_path):
    path = tmp_path / "pc.csv"
    path.write_text("email\na@b.org\n")
    with pytest.raises(inputs.InputError, match="first, last"):
        inputs.read_people(path, with_paper=False)


def test_review_xml_keeps_scores_apart_and_decodes_entities_and_cdata():
    reviews = {r.review_id: r for r in inputs.read_reviews(EASYCHAIR)}
    first, second = reviews["rev0007a"], reviews["rev0007b"]
    assert first.paper_id == 7 and first.title == "Flaky Tests & Their Fixes"
    assert first.scores == {"Overall evaluation": "-1", "Reviewer's confidence": "4"}
    assert "<with> CDATA" in second.author_text


def test_author_text_leaves_out_committee_fields_and_field_names():
    review = next(r for r in inputs.read_reviews(EASYCHAIR) if r.review_id == "rev0007a")
    assert "I may know the authors" not in review.author_text
    assert "Paper Summary" not in review.author_text
    assert review.author_text.startswith("The paper studies flaky tests")
    assert "Table 3 mixes two units." in review.author_text


def test_empty_reviewer_fields_give_no_reviewer():
    reviews = {r.review_id: r for r in inputs.read_reviews(EASYCHAIR)}
    assert reviews["rev0007a"].reviewer is None
    assert reviews["rev0007b"].reviewer.email == "dana@example.org"


HOTCRP = Path(__file__).parent / "fixtures" / "hotcrp" / "reviews.csv"


def test_hotcrp_review_export_gives_the_scores_the_text_for_authors_and_the_reviewer():
    first, second = inputs.read_reviews(HOTCRP)
    assert (first.review_id, first.paper_id, second.review_id) == ("12A", 12, "12B")
    assert first.scores == {"Overall merit": "3", "Reviewer expertise": "2"}
    assert "lacks a baseline" in first.author_text and "unsure about the novelty" not in first.author_text
    assert (first.reviewer.last, first.reviewer.email) == ("Roe", "jane.roe@example.org")


def test_review_folder_reads_easychair_xml_and_hotcrp_csv_together(tmp_path):
    for source in [HOTCRP, *EASYCHAIR.glob("review_*.xml")]:
        (tmp_path / source.name).write_bytes(source.read_bytes())
    sources = {review.source for review in inputs.read_reviews(tmp_path)}
    assert "reviews.csv" in sources and any(name.endswith(".xml") for name in sources)


def test_review_csv_without_a_paper_column_is_refused(tmp_path):
    path = tmp_path / "reviews.csv"
    path.write_text("title,Overall merit\nA paper,3\n")
    with pytest.raises(inputs.InputError, match="column paper"):
        inputs.read_reviews(path)


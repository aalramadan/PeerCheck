"""Tests of the readers for PDFs and the CSV files of submissions, people, and reviews."""

import dataclasses
import shutil
from pathlib import Path

import pytest

from peercheck import inputs, profile

FIXTURES = Path(__file__).parent / "fixtures"
EASYCHAIR = FIXTURES / "easychair"


def test_pdfs_take_the_paper_number_of_their_names_and_a_repeated_number_is_skipped(tmp_path):
    source = FIXTURES / "papers" / "corrupt.pdf"
    for name in ("CONF_2026_paper_0041.pdf", "CONF_2026_paper_41.pdf", "CONF_2026_paper_0042 (1).pdf",
                 "conf_2026_paper_0043.PDF", "notes.txt"):
        shutil.copy(source, tmp_path / name)
    found = inputs.find_pdfs(tmp_path)
    assert sorted(found.papers) == [41, 42, 43]
    assert found.numbered == {}
    assert len(found.duplicates) == 1


def test_pdfs_whose_names_hold_no_paper_number_get_the_next_free_numbers(tmp_path):
    for name in ("CONF27_paper__3.pdf", "12.pdf", "smith-study.pdf", "notes.pdf"):
        shutil.copy(FIXTURES / "papers" / "corrupt.pdf", tmp_path / name)
    found = inputs.find_pdfs(tmp_path)
    assert sorted(found.papers) == [3, 12, 13, 14]
    assert found.numbered == {13: "notes.pdf", 14: "smith-study.pdf"}


def test_missing_pdf_folder_is_an_input_error(tmp_path):
    with pytest.raises(inputs.InputError, match="not found"):
        inputs.find_pdfs(tmp_path / "missing", profile.load("icse-2027"))


def test_pdf_given_in_place_of_the_folder_is_an_input_error_that_asks_for_the_folder(tmp_path):
    (tmp_path / "paper1.pdf").write_bytes(b"%PDF-1.4")
    with pytest.raises(inputs.InputError, match="paper1.pdf is a file; give the folder that holds the PDFs"):
        inputs.find_pdfs(tmp_path / "paper1.pdf")


def test_pdf_folder_skips_the_dot_files_of_macos(tmp_path):
    for name in ("CONF_2026_paper_0041.pdf", "._CONF_2026_paper_0041.pdf"):
        shutil.copy(FIXTURES / "papers" / "corrupt.pdf", tmp_path / name)
    found = inputs.find_pdfs(tmp_path, profile.load("icse-2027"))
    assert (found.papers[41].name, found.duplicates) == ("CONF_2026_paper_0041.pdf", [])


def test_pdf_paths_are_absolute_for_a_relative_folder(tmp_path, monkeypatch):
    shutil.copy(FIXTURES / "papers" / "corrupt.pdf", tmp_path / "-CONF_2026_paper_0041.pdf")
    monkeypatch.chdir(tmp_path)
    assert inputs.find_pdfs(Path("."), profile.load("icse-2027")).papers[41].is_absolute()


def test_submission_sheet_gives_titles_by_id():
    titles = inputs.read_submissions(EASYCHAIR / "submissions.csv", profile.load("icse-2027"))
    assert set(titles) == {7, 8}


def test_submission_sheet_without_the_id_column_names_the_column(tmp_path):
    path = tmp_path / "s.csv"
    path.write_text("Number,Title\n1,A\n")
    with pytest.raises(inputs.InputError, match="no column of paper IDs"):
        inputs.read_submissions(path)


@pytest.mark.parametrize("header", ["#,Title,paper", "ID,Title"])
def test_submission_sheet_of_either_system_gives_titles_without_a_profile(tmp_path, header):
    path = tmp_path / "submissions.csv"
    path.write_text(f"{header}\n7,A,A.pdf\n8,B,B.pdf\n")
    assert inputs.read_submissions(path) == {7: "A", 8: "B"}


def test_id_column_of_the_profile_overrides_the_search_of_the_sheet(tmp_path):
    path = tmp_path / "submissions.csv"
    path.write_text("#,Submission,Title\n1,7,A\n")
    venue = dataclasses.replace(profile.load("icse-2027"), id_column="Submission")
    assert inputs.read_submissions(path, venue) == {7: "A"}


def test_easychair_author_headers_are_understood():
    authors = inputs.read_people(EASYCHAIR / "authors.csv", with_paper=True)
    assert [a.name for a in authors[7]] == ["Maria Lindqvist", "Wei Zhang"]
    assert authors[7][0].affiliation == "KTH Royal Institute of Technology"


def test_people_list_without_names_is_rejected(tmp_path):
    path = tmp_path / "pc.csv"
    path.write_text("email\na@b.org\n")
    with pytest.raises(inputs.InputError, match="first, last"):
        inputs.read_people(path, with_paper=False)


def test_email_affiliation_and_dblp_are_found_under_longer_headers(tmp_path):
    authors, pc = tmp_path / "authors.csv", tmp_path / "pc.csv"
    authors.write_text("Paper ID,First Name,Last Name,E-mail Address,Affiliations\n"
                       "7,Jun,Takeda,jun@riverside.example,Riverside State University\n")
    pc.write_text("First Name,Last Name,Primary Email,Institution/Organization,DBLP profile\n"
                  "Ana,Ruiz,ana@riverside.example,Riverside State University,https://dblp.org/pid/12/3456.html\n")
    author = inputs.read_people(authors, with_paper=True)[7][0]
    (member,) = inputs.read_people(pc, with_paper=False)
    assert (author.email, author.affiliation) == ("jun@riverside.example", "Riverside State University")
    assert (member.email, member.affiliation, member.dblp) == (
        "ana@riverside.example", "Riverside State University", "https://dblp.org/pid/12/3456.html")


def test_people_list_without_email_or_affiliation_is_reported(tmp_path, capsys):
    path = tmp_path / "pc.csv"
    path.write_text("first,last,Company\nAna,Ruiz,Riverside Labs\n")
    inputs.read_people(path, with_paper=False)
    message = capsys.readouterr().err
    assert "pc.csv" in message and "email" in message and "affiliation" in message


@pytest.mark.parametrize("delimiter", [";", "\t"])
def test_semicolon_and_tab_separated_lists_are_read(tmp_path, delimiter):
    path = tmp_path / "authors.csv"
    path.write_text(f"paper{delimiter}first{delimiter}last\n7{delimiter}Ana{delimiter}Ruiz\n")
    assert [author.name for author in inputs.read_people(path, with_paper=True)[7]] == ["Ana Ruiz"]


@pytest.mark.parametrize("encoding, delimiter", [("cp1252", ","), ("utf-16", "\t")])
def test_lists_that_excel_saves_in_windows_or_unicode_encoding_are_read(tmp_path, encoding, delimiter):
    path = tmp_path / "authors.csv"
    text = f"paper{delimiter}first{delimiter}last\r\n7{delimiter}Jürgen{delimiter}Müller\r\n"
    path.write_bytes(text.encode(encoding))
    assert [author.name for author in inputs.read_people(path, with_paper=True)[7]] == ["Jürgen Müller"]


def test_list_in_an_unknown_encoding_is_an_input_error_naming_the_file(tmp_path):
    path = tmp_path / "authors.csv"
    path.write_bytes(b"paper,first,last\n7,\x81\x8d,\x90\n")
    with pytest.raises(inputs.InputError, match="authors.csv"):
        inputs.read_people(path, with_paper=True)


def test_paper_ids_with_a_thousands_separator_a_hash_or_decimals_are_read(tmp_path):
    path = tmp_path / "authors.csv"
    cells = ["1 234", "1\xa0234", "1 234", "1,234", "#7", "12.00"]
    path.write_text("paper,first,last\n" + "".join(f'"{cell}",First,Last{i}\n' for i, cell in enumerate(cells)),
                    encoding="utf-8")
    assert sorted(inputs.read_people(path, with_paper=True)) == [7, 12, 1234]


def test_author_rows_without_a_paper_id_are_counted_in_an_error(tmp_path):
    path = tmp_path / "authors.csv"
    path.write_text("paper,first,last\n7,Ana,Ruiz\n7a,Bo,Lee\nPaper 8,Cy,Kim\n")
    with pytest.raises(inputs.InputError, match="2 of 3 rows"):
        inputs.read_people(path, with_paper=True)


@pytest.mark.parametrize("title, number", [("Paper", "Paper ID"), ("Submission", "Submission #")])
def test_id_column_with_numbers_wins_over_a_title_column_named_paper(tmp_path, title, number):
    path = tmp_path / "authors.csv"
    path.write_text(f"{title},{number},First name,Last name\nFlaky Tests in Practice,7,Ana,Ruiz\n")
    assert [author.name for author in inputs.read_people(path, with_paper=True)[7]] == ["Ana Ruiz"]


HEADER = ["paper", "first", "last", "email"]
AUTHORS = [[7, "Maria", "Lindqvist"], [8, "Wei", "Zhang", "wei@example.edu"], [9, "Omar", "Haddad", "omar@example.com"]]


def test_csv_list_may_start_below_a_blank_row(tmp_path):
    path = tmp_path / "authors.csv"
    path.write_text("\n" + "\n".join(",".join(map(str, row)) for row in [HEADER, *AUTHORS]) + "\n")
    assert sorted(inputs.read_people(path, with_paper=True)) == [7, 8, 9]


@pytest.mark.parametrize("name", ["authors.xlsx", "authors.xls"])
def test_excel_files_are_refused_with_the_advice_to_save_them_as_csv(tmp_path, name):
    path = tmp_path / name
    path.write_bytes(b"PK\x03\x04" + bytes(64))
    with pytest.raises(inputs.InputError, match=rf"{name} is an Excel file; save it as CSV"):
        inputs.read_people(path, with_paper=True)


def test_review_csv_keeps_scores_apart_from_the_text_and_keeps_the_title():
    reviews = {r.review_id: r for r in inputs.read_reviews(EASYCHAIR / "reviews.csv")}
    first, second = reviews["7A"], reviews["7B"]
    assert first.paper_id == 7 and first.title == "Flaky Tests & Their Fixes"
    assert first.scores == {"Overall evaluation": "-1", "Reviewer's confidence": "4"}
    assert "<with> CDATA" in second.author_text


def test_author_text_leaves_out_committee_fields_and_field_names():
    review = next(r for r in inputs.read_reviews(EASYCHAIR / "reviews.csv") if r.review_id == "7A")
    assert "I may know the authors" not in review.author_text
    assert "Paper Summary" not in review.author_text
    assert review.author_text.startswith("The paper studies flaky tests")
    assert "Table 3 mixes two units." in review.author_text


def test_empty_reviewer_fields_give_no_reviewer():
    reviews = {r.review_id: r for r in inputs.read_reviews(EASYCHAIR / "reviews.csv")}
    assert reviews["7A"].reviewer is None
    assert reviews["7B"].reviewer.email == "dana@example.org"


HOTCRP = Path(__file__).parent / "fixtures" / "hotcrp" / "reviews.csv"


def test_hotcrp_review_export_gives_the_scores_the_text_for_authors_and_the_reviewer():
    first, second = inputs.read_reviews(HOTCRP)
    assert (first.review_id, first.paper_id, second.review_id) == ("12A", 12, "12B")
    assert first.scores == {"Overall merit": "3", "Reviewer expertise": "2"}
    assert "lacks a baseline" in first.author_text and "unsure about the novelty" not in first.author_text
    assert (first.reviewer.last, first.reviewer.email) == ("Roe", "jane.roe@example.org")


def test_reviews_come_from_one_csv_file_never_a_folder(tmp_path):
    (tmp_path / "reviews.csv").mkdir()
    with pytest.raises(inputs.InputError, match="is a folder; --reviews takes the CSV file of the reviews"):
        inputs.read_reviews(tmp_path / "reviews.csv")


@pytest.mark.parametrize(("name", "message"), [("review_0007_1.xml", "is no CSV file"),
                                               ("reviews.xlsx", "is an Excel file; save it as CSV")])
def test_review_file_in_another_format_is_refused_with_what_to_do(tmp_path, name, message):
    path = tmp_path / name
    path.write_bytes(b"<review submission='7'/>")
    with pytest.raises(inputs.InputError, match=message):
        inputs.read_reviews(path)


def test_review_csv_keeps_negative_scores_apart_from_the_text_for_authors(tmp_path):
    path = tmp_path / "reviews.csv"
    path.write_text("paper,review,Overall evaluation,Comments for authors\n101,A,-2,The paper is weak.\n"
                    "102,A,1,The paper is fine.\n")
    first, second = inputs.read_reviews(path)
    assert (first.scores, second.scores) == ({"Overall evaluation": "-2"}, {"Overall evaluation": "1"})
    assert first.author_text == "The paper is weak."


def test_review_csv_column_without_any_value_counts_as_no_score(tmp_path):
    path = tmp_path / "reviews.csv"
    path.write_text("paper,review,Overall evaluation,Questions for authors,Comments for authors\n"
                    "101,A,2,,The paper is fine.\n")
    (review,) = inputs.read_reviews(path)
    assert review.scores == {"Overall evaluation": "2"}


def test_review_csv_without_a_paper_column_is_refused(tmp_path):
    path = tmp_path / "reviews.csv"
    path.write_text("title,Overall merit\nA paper,3\n")
    with pytest.raises(inputs.InputError, match="column paper"):
        inputs.read_reviews(path)


def test_hotcrp_review_numbers_are_kept_apart_from_the_paper_number(tmp_path):
    path = tmp_path / "reviews.csv"
    path.write_text("paper,title,review,Comments for authors\n101,P,2,The first review.\n10,Q,12,The second review.\n")
    assert [review.review_id for review in inputs.read_reviews(path)] == ["101-2", "10-12"]


def test_review_column_as_hotcrp_writes_it_gives_ids_such_as_12a(tmp_path):
    path = tmp_path / "reviews.csv"
    path.write_text("paper,title,review,Comments for authors\n12,A Paper,12A,The first review.\n"
                    "12,A Paper,12B,The second review.\n")
    assert [review.review_id for review in inputs.read_reviews(path)] == ["12A", "12B"]


def test_short_hotcrp_answers_stay_text_while_a_score_may_carry_a_description(tmp_path):
    path = tmp_path / "reviews.csv"
    path.write_text("paper,title,review,Overall merit,Comments for authors,Questions for authors\n"
                    "5,A,A,3. Weak accept,I am not convinced by the evaluation in Section 4.,No questions.\n"
                    "6,B,A,2. Weak reject,An interesting idea; the baseline is too weak.,Is the tool public?\n")
    first, second = inputs.read_reviews(path)
    assert (first.scores, second.scores) == ({"Overall merit": "3. Weak accept"}, {"Overall merit": "2. Weak reject"})
    assert first.author_text == "I am not convinced by the evaluation in Section 4.\n\nNo questions."
    assert second.author_text.endswith("Is the tool public?")


def test_semicolon_separated_review_export_is_read(tmp_path):
    path = tmp_path / "reviews.csv"
    path.write_text("paper;title;review;Comments for authors\n12;A Paper;A;The evaluation lacks a baseline.\n")
    assert [review.review_id for review in inputs.read_reviews(path)] == ["12A"]


def test_review_export_with_capitalized_headers_is_read(tmp_path):
    path = tmp_path / "reviews.csv"
    path.write_text("Paper,Title,Review,Comments for authors\n101,Paper 101,B,The evaluation lacks a baseline.\n")
    assert [review.review_id for review in inputs.read_reviews(path)] == ["101B"]


def test_header_only_review_export_gives_no_reviews(tmp_path):
    path = tmp_path / "reviews.csv"
    path.write_text("paper,title,review,reviewername,email,Overall merit\n")
    assert inputs.read_reviews(path) == []


def test_review_export_skips_rows_without_values(tmp_path):
    path = tmp_path / "reviews.csv"
    path.write_text("paper,title,review,Comments for authors\r\n12,A Paper,A,The evaluation lacks a baseline.\r\n"
                    ",,,\r\n,,,\r\n")
    assert [review.review_id for review in inputs.read_reviews(path)] == ["12A"]


def test_review_csv_without_a_review_column_is_refused(tmp_path):
    path = tmp_path / "reviews.csv"
    path.write_text("paper,title,Comments for authors\n12,A Paper,The evaluation lacks a baseline.\n")
    with pytest.raises(inputs.InputError, match="column review"):
        inputs.read_reviews(path)


def test_review_text_in_the_review_column_is_reported(tmp_path, capsys):
    path = tmp_path / "reviews.csv"
    path.write_text('paper,review\n101,"This paper ranks flaky test failures. The evaluation is sound."\n')
    inputs.read_reviews(path)
    assert "column review" in capsys.readouterr().err


@pytest.mark.parametrize("name, for_authors", [
    ("Comments for PC", False),
    ("Confidential remarks for the program committee", False),
    ("Private comments to the program chairs", False),
    ("Comments to the chairs", False),
    ("Comments for the AC", False),
    ("Comments for PC (hidden from authors)", False),
    ("Comments for authors and PC", True),
    ("Summary for the authors (shown to the PC)", True),
])
def test_field_names_decide_which_text_goes_to_the_authors(tmp_path, name, for_authors):
    path = tmp_path / "reviews.csv"
    path.write_text(f"paper,review,{name}\n12,A,The evaluation lacks a baseline.\n")
    (review,) = inputs.read_reviews(path)
    assert bool(review.author_text) is for_authors


def test_author_list_of_hotcrp_with_given_and_family_names_is_read(tmp_path):
    path = tmp_path / "authors.csv"
    path.write_text("paper,title,given_name,family_name,email,affiliation\n"
                    "4,Flaky Tests,Ana,Ruiz,ana@riverside.example,Riverside State University\n", encoding="utf-8")
    person = inputs.read_people(path, with_paper=True)[4][0]
    assert (person.first, person.last, person.email) == ("Ana", "Ruiz", "ana@riverside.example")

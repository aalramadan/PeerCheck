"""Tests of the readers for PDFs, submission sheets, people lists, and EasyChair review XML."""

import dataclasses
import re
import shutil
import zipfile
from pathlib import Path

import openpyxl
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


def test_excel_list_comes_from_the_first_visible_sheet(tmp_path):
    book = openpyxl.Workbook()
    book.active.append(HEADER)
    book.active.append([7, "Old", "Author"])
    book.active.sheet_state = "hidden"
    current = book.create_sheet("2027")
    for row in [HEADER, *AUTHORS]:
        current.append(row)
    book.active = 1
    book.save(tmp_path / "authors.xlsx")
    assert sorted(inputs.read_people(tmp_path / "authors.xlsx", with_paper=True)) == [7, 8, 9]


def test_excel_list_may_start_below_a_blank_row(tmp_path):
    book = openpyxl.Workbook()
    for index, row in enumerate([HEADER, *AUTHORS], start=2):
        for column, value in enumerate(row, start=1):
            book.active.cell(index, column, value)
    book.save(tmp_path / "authors.xlsx")
    assert sorted(inputs.read_people(tmp_path / "authors.xlsx", with_paper=True)) == [7, 8, 9]


def test_excel_list_is_read_whole_despite_a_wrong_sheet_size(tmp_path):
    written, path = tmp_path / "written.xlsx", tmp_path / "authors.xlsx"
    book = openpyxl.Workbook()
    for row in [HEADER, *AUTHORS]:
        book.active.append(row)
    book.save(written)
    with zipfile.ZipFile(written) as source, zipfile.ZipFile(path, "w") as target:
        for item in source.infolist():
            data = source.read(item.filename)
            if item.filename == "xl/worksheets/sheet1.xml":
                data = re.sub(rb'<dimension ref="[^"]*"/>', b'<dimension ref="A1:D2"/>', data)
            target.writestr(item, data)
    authors = inputs.read_people(path, with_paper=True)
    assert sorted(authors) == [7, 8, 9] and authors[8][0].email == "wei@example.edu"


def test_csv_text_under_an_excel_name_is_an_input_error_naming_the_file(tmp_path):
    path = tmp_path / "authors.xlsx"
    path.write_text("paper,first,last\n7,Ana,Ruiz\n")
    with pytest.raises(inputs.InputError, match="authors.xlsx"):
        inputs.read_people(path, with_paper=True)


def test_old_excel_workbooks_are_refused_with_a_clear_message(tmp_path):
    path = tmp_path / "authors.xls"
    path.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + bytes(512))
    with pytest.raises(inputs.InputError, match=r"authors\.xls .*\.xlsx"):
        inputs.read_people(path, with_paper=True)


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


def test_hotcrp_review_numbers_are_kept_apart_from_the_paper_number(tmp_path):
    path = tmp_path / "reviews.csv"
    path.write_text("paper,title,review,Comments for authors\n101,P,2,The first review.\n10,Q,12,The second review.\n")
    assert [review.review_id for review in inputs.read_reviews(path)] == ["101-2", "10-12"]


def test_review_column_as_hotcrp_writes_it_gives_ids_such_as_12a(tmp_path):
    path = tmp_path / "reviews.csv"
    path.write_text("paper,title,review,Comments for authors\n12,A Paper,12A,The first review.\n"
                    "12,A Paper,12B,The second review.\n")
    assert [review.review_id for review in inputs.read_reviews(path)] == ["12A", "12B"]


def test_easychair_reviews_without_an_id_are_named_by_file_and_position(tmp_path):
    review = '<review submission="{}"><field name="Comments"><text>Review {}.</text></field></review>'
    reviews = "".join(review.format(paper, number) for number, paper in enumerate((1, 1, 2), start=1))
    (tmp_path / "reviews.xml").write_text(f"<reviews>{reviews}</reviews>")
    assert [review.review_id for review in inputs.read_reviews(tmp_path)] == ["reviews-1", "reviews-2", "reviews-3"]


def test_short_hotcrp_answers_stay_text_while_a_score_may_carry_a_description(tmp_path):
    path = tmp_path / "reviews.csv"
    path.write_text("paper,title,review,Overall merit,Comments for authors,Questions for authors\n"
                    "5,A,A,3. Weak accept,I am not convinced by the evaluation in Section 4.,No questions.\n"
                    "6,B,A,2. Weak reject,An interesting idea; the baseline is too weak.,Is the tool public?\n")
    first, second = inputs.read_reviews(path)
    assert (first.scores, second.scores) == ({"Overall merit": "3. Weak accept"}, {"Overall merit": "2. Weak reject"})
    assert first.author_text == "I am not convinced by the evaluation in Section 4.\n\nNo questions."
    assert second.author_text.endswith("Is the tool public?")


def test_semicolon_separated_review_export_is_read_from_a_folder(tmp_path):
    (tmp_path / "reviews.csv").write_text("paper;title;review;Comments for authors\n"
                                          "12;A Paper;A;The evaluation lacks a baseline.\n")
    assert [review.review_id for review in inputs.read_reviews(tmp_path)] == ["12A"]


def test_review_folder_skips_the_dot_files_of_macos(tmp_path):
    shutil.copy(EASYCHAIR / "review_0007_1.xml", tmp_path)
    (tmp_path / "._review_0007_1.xml").write_bytes(b"\x00\x05\x16\x07\x00\x02\x00\x00Mac OS X        ")
    assert [review.review_id for review in inputs.read_reviews(tmp_path)] == ["rev0007a"]


def test_broken_review_xml_is_an_input_error_naming_the_file(tmp_path):
    (tmp_path / "review_0201_1.xml").write_text("<review id='1' submission='201'><field name='x'><text>cut")
    with pytest.raises(inputs.InputError, match="review_0201_1.xml"):
        inputs.read_reviews(tmp_path)


def test_review_folder_skips_other_csv_files_whatever_their_encoding(tmp_path, capsys):
    shutil.copy(HOTCRP, tmp_path / "reviews.csv")
    (tmp_path / "authors.csv").write_bytes("Submission #,First name,Last name\r\n101,Renée,Façade\r\n".encode("cp1252"))
    (tmp_path / "notes.csv").write_bytes(b"\x81\x8d\x90")
    assert [review.review_id for review in inputs.read_reviews(tmp_path)] == ["12A", "12B"]
    assert "notes.csv" in capsys.readouterr().err


def test_review_export_with_capitalized_headers_is_read_as_a_file_and_from_a_folder(tmp_path):
    path = tmp_path / "reviews.csv"
    path.write_text("Paper,Title,Review,Comments for authors\n101,Paper 101,B,The evaluation lacks a baseline.\n")
    assert [review.review_id for review in inputs.read_reviews(path)] == ["101B"]
    assert [review.review_id for review in inputs.read_reviews(tmp_path)] == ["101B"]


def test_header_only_review_export_gives_no_reviews(tmp_path):
    shutil.copy(EASYCHAIR / "review_0007_1.xml", tmp_path)
    (tmp_path / "track2.csv").write_text("paper,title,review,reviewername,email,Overall merit\n")
    assert inputs.read_reviews(tmp_path / "track2.csv") == []
    assert [review.review_id for review in inputs.read_reviews(tmp_path)] == ["rev0007a"]


def test_review_export_skips_rows_without_values(tmp_path):
    path = tmp_path / "reviews.csv"
    path.write_text("paper,title,review,Comments for authors\r\n12,A Paper,A,The evaluation lacks a baseline.\r\n"
                    ",,,\r\n,,,\r\n")
    assert [review.review_id for review in inputs.read_reviews(path)] == ["12A"]


def test_review_csv_without_a_review_column_is_refused_as_a_file_and_skipped_in_a_folder(tmp_path, capsys):
    path = tmp_path / "reviews.csv"
    path.write_text("paper,title,Comments for authors\n12,A Paper,The evaluation lacks a baseline.\n")
    with pytest.raises(inputs.InputError, match="column review"):
        inputs.read_reviews(path)
    assert inputs.read_reviews(tmp_path) == []
    assert "reviews.csv" in capsys.readouterr().err


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

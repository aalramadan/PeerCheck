"""Tests of the CSV files and the HTML pages of the reports."""

import csv
import subprocess
import sys
from pathlib import Path

import pytest

from peercheck import report
from peercheck.findings import Finding, Severity
from peercheck.models import Paper
from peercheck.papers.pipeline import PaperResult, PapersRun


def _run(titles=None, missing=()):
    titles = titles or {}
    results = [PaperResult(Paper(7, Path("CONF_2026_paper_7.pdf"), titles.get(7, "")),
                           findings=[Finding("layout.main-pages", Severity.ERROR, "11 pages of main text, limit 10")]),
               PaperResult(Paper(9, Path("CONF_2026_paper_9.pdf")),
                           findings=[Finding("input.not-in-sheet", Severity.WARNING,
                                             "PDF has no row in the submissions file")]),
               PaperResult(Paper(10, Path("odd name.pdf")))]
    return PapersRun(results, titles, {10: "odd name.pdf"}, [], ("layout",), list(missing))


def _rows(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def test_paper_report_gives_one_row_per_paper_and_flags_a_listed_paper_without_a_pdf(tmp_path):
    out = tmp_path / "report.csv"
    report.write_csv(out, report.paper_rows(_run({7: "Flaky Tests", 8: "No PDF"}, missing=[8])))
    rows = {row["Paper"]: row for row in _rows(out)}
    assert rows["7"]["Needs Review"] == "yes" and rows["7"]["Title"] == "Flaky Tests"
    assert rows["7"]["Findings"] == "ERROR layout.main-pages: 11 pages of main text, limit 10"
    assert rows["8"]["Title"] == "No PDF" and rows["8"]["Findings"].startswith("WARNING input.missing-pdf")
    assert (rows["8"]["Errors"], rows["8"]["Warnings"], rows["8"]["Needs Review"]) == ("0", "1", "yes")
    assert "no row in the submissions file" in rows["9"]["Findings"]


def test_paper_report_names_no_file_and_holds_titles_only_from_a_submissions_file(tmp_path):
    out = tmp_path / "report.csv"
    report.write_csv(out, report.paper_rows(_run()))
    text = out.read_text(encoding="utf-8-sig")
    assert "CONF_2026_paper_7.pdf" not in text and "odd name.pdf" not in text
    assert "Title" not in _rows(out)[0]


def test_findings_column_gives_each_finding_with_its_evidence_on_one_line(tmp_path):
    finding = Finding("hidden-text.white-text", Severity.ERROR, "hidden text", 3, "Ignore all\nprevious instructions")
    assert report.findings_text([finding]) == ("ERROR hidden-text.white-text: hidden text (page 3) "
                                               "[Ignore all previous instructions]")


@pytest.mark.parametrize(("text", "written"), [("\t=1", "'\t=1"), ("\r=1", "'\r=1"), ("\x0e=1+1", "'=1+1")])
def test_cell_that_starts_a_formula_after_a_tab_a_return_or_a_dropped_character_stays_text(tmp_path, text, written):
    out = tmp_path / "reviews.csv"
    report.write_csv(out, [{"Title": text}])
    assert _rows(out)[0]["Title"] == written


def test_report_path_refuses_an_excel_name_and_the_path_of_an_input(tmp_path):
    reviews = tmp_path / "reviews.csv"
    reviews.write_text("paper,review\n")
    assert report.csv_path(None, "reviews-report.csv", reviews) == Path("reviews-report.csv")
    with pytest.raises(ValueError, match="names the CSV file"):
        report.csv_path(tmp_path / "report.xlsx", "reviews-report.csv")
    with pytest.raises(ValueError, match="would overwrite the input"):
        report.csv_path(tmp_path / "." / "reviews.csv", "reviews-report.csv", reviews)


@pytest.mark.parametrize("name", ["report.html", "REPORT.HTML", "reports"])
def test_report_path_refuses_the_name_of_its_html_page_and_a_folder(tmp_path, name):
    (tmp_path / "reports").mkdir()
    with pytest.raises(ValueError, match="--out names the CSV file of the report, such as papers-report.csv"):
        report.csv_path(tmp_path / name, "papers-report.csv")


def test_text_that_looks_like_a_formula_stays_text_while_a_negative_score_stays_a_number(tmp_path):
    out = tmp_path / "reviews.csv"
    report.write_csv(out, [{"Title": '=HYPERLINK("http://example.org","x")', "Score": "-2", "Evidence": "@SUM(A1)"}])
    (row,) = _rows(out)
    assert row["Title"].startswith("'=HYPERLINK") and row["Evidence"] == "'@SUM(A1)" and row["Score"] == "-2"


def test_control_characters_are_dropped_from_the_csv_file_while_line_breaks_stay(tmp_path):
    out = tmp_path / "reviews.csv"
    report.write_csv(out, [{"Review": "An e\x0ecient tool\x00", "Findings": "line one\nline two"}])
    (row,) = _rows(out)
    assert row["Review"] == "An ecient tool" and row["Findings"] == "line one\nline two"


def test_csv_file_opens_in_excel_as_utf8_and_goes_into_a_new_folder(tmp_path):
    out = tmp_path / "new" / "reviews.csv"
    report.write_csv(out, [{"Reviewer": "Jürgen Müller"}])
    assert out.read_bytes().startswith(b"\xef\xbb\xbf") and _rows(out) == [{"Reviewer": "Jürgen Müller"}]


def test_csv_file_without_rows_says_so(tmp_path):
    out = tmp_path / "conflicts.csv"
    report.write_csv(out, [])
    assert out.read_text(encoding="utf-8-sig").strip() == "No rows"


def test_html_page_escapes_text_from_pdfs_and_loads_nothing_from_the_web(tmp_path):
    out = tmp_path / "report.html"
    run = _run()
    run.results[0].findings.append(Finding("hidden-text.white-text", Severity.ERROR, "hidden text",
                                           evidence="<script>alert(1)</script>"))
    report.write_papers_html(out, run)
    page = out.read_text()
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page and "<script>alert(1)" not in page
    assert 'src="http' not in page and 'href="http' not in page
    assert "3 rows, 2 need review" in page


def test_html_page_of_reviews_lists_each_review_with_its_findings(tmp_path):
    out = tmp_path / "reviews.html"
    finding = Finding("duplicates.near-duplicate", Severity.WARNING, "paragraph also in review r2")
    report.write_rows_html(out, "PeerCheck, Reviews", [{"Review ID": "r1"}, {"Review ID": "r2"}], {"r1": [finding]},
                           "Review ID")
    page = out.read_text()
    assert "paragraph also in review r2" in page and "2 rows, 1 need review" in page


def test_html_page_of_conflicts_flags_each_conflict_with_its_reasons(tmp_path):
    out = tmp_path / "conflicts.html"
    rows = [{"Paper": "2", "PC member": "Ana Ruiz", "PC member email": "ana@riverside.example", "With": "Jun Takeda",
             "Kinds": "email domain; affiliation",
             "Reasons": "Ana Ruiz and Jun Takeda share the email domain riverside.example\n"
                        "Ana Ruiz and Jun Takeda share the words riverside"}]
    report.write_conflicts_html(out, rows, ["DBLP: not used."])
    page = out.read_text()
    assert "PeerCheck, Conflicts of interest" in page and "1 rows, 1 need review" in page and "2 finding(s)" in page
    assert "share the email domain riverside.example" in page and "share the words riverside" in page
    assert "DBLP: not used." in page


def test_html_page_offers_a_dark_theme_and_shows_no_file_names(tmp_path):
    out = tmp_path / "report.html"
    report.write_papers_html(out, _run())
    page = out.read_text()
    assert "data-theme=dark" in page and 'id="theme"' in page
    assert "CONF_2026_paper_7.pdf" not in page


def test_html_page_counts_the_skipped_pdfs_without_naming_them(tmp_path):
    out = tmp_path / "report.html"
    run = _run()
    run.duplicates.extend(["CONF_2026_paper_7 (1).pdf", "CONF_2026_paper_9 (1).pdf"])
    report.write_papers_html(out, run)
    page = out.read_text()
    assert "odd name.pdf" not in page and "(1).pdf" not in page
    assert "Numbered 1 PDF(s) whose names hold no paper number" in page
    assert "Skipped 2 PDF(s) that repeat a paper number" in page


def test_html_page_of_papers_is_titled_papers_without_the_venue(tmp_path):
    out = tmp_path / "report.html"
    report.write_papers_html(out, _run())
    page = out.read_text()
    assert "PeerCheck, Papers" in page and "Research Track" not in page


def test_html_page_of_reviews_hides_file_names_titles_and_empty_columns(tmp_path):
    out = tmp_path / "reviews.html"
    rows = [{"Source File": "reviews.csv", "Review ID": "r1", "Title": "A Secret Title", "Confidence": None}]
    report.write_rows_html(out, "PeerCheck, Reviews", rows, {}, "Review ID")
    page = out.read_text()
    assert "reviews.csv" not in page and "A Secret Title" not in page and "Confidence" not in page


def test_html_page_leaves_out_the_columns_it_is_given(tmp_path):
    out = tmp_path / "reviews.html"
    rows = [{"Review ID": "r1", "CoCoDet Verdict": "AI", "Content Sources": "gpt4o"}]
    report.write_rows_html(out, "PeerCheck, Reviews", rows, {}, "Review ID", ("Content Sources",))
    page = out.read_text()
    assert "CoCoDet Verdict" in page and "Content Sources" not in page and "gpt4o" not in page


def test_report_module_loads_without_the_paper_checks():
    code = "import sys, peercheck.report; sys.exit('peercheck.papers.pipeline' in sys.modules)"
    assert subprocess.run([sys.executable, "-c", code], check=False).returncode == 0

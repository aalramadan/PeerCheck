"""Tests of the Excel and JSON reports."""

import json
from pathlib import Path

import openpyxl

from peercheck import profile, report
from peercheck.findings import Finding, Severity
from peercheck.models import Paper
from peercheck.pipeline import PaperResult, PapersRun

EASYCHAIR = Path(__file__).parent / "fixtures" / "easychair"


def _run():
    results = [PaperResult(Paper(7, Path("CONF_2026_paper_7.pdf")),
                           findings=[Finding("layout.main-pages", Severity.ERROR, "11 pages of main text, limit 10")]),
               PaperResult(Paper(9, Path("CONF_2026_paper_9.pdf")),
                           findings=[Finding("input.not-in-sheet", Severity.WARNING,
                                             "PDF has no row in the submission sheet")])]
    return PapersRun(results, {}, {10: "odd name.pdf"}, [], ("layout",))


def _submissions(tmp_path):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    for row in [("#", "Title"), (7, "=HYPERLINK(\"http://example.org\")"), (8, "No PDF")]:
        sheet.append(row)
    path = tmp_path / "submissions.xlsx"
    workbook.save(path)
    return path


def _sheet(path, title):
    workbook = openpyxl.load_workbook(path)
    return workbook[title] if title else workbook.worksheets[0]


def test_report_extends_the_submission_sheet_and_flags_missing_and_extra_pdfs(tmp_path):
    out = tmp_path / "report.xlsx"
    report.write_papers(out, _run(), profile.load("icse-2027"), _submissions(tmp_path))
    rows = {row[0]: row for row in _sheet(out, None).iter_rows(min_row=2, values_only=True)}
    header = [c.value for c in _sheet(out, None)[1]]
    findings = header.index("Findings")
    assert rows[7][header.index("Needs Review")] == "yes"
    assert "11 pages of main text" in rows[7][findings]
    assert rows[8][findings] == "WARNING: missing PDF"
    assert "no row in the submission sheet" in rows[9][findings]


def test_text_from_reviews_and_pdfs_that_looks_like_a_formula_stays_text(tmp_path):
    out = tmp_path / "reviews.xlsx"
    finding = Finding("hidden-text.white-text", Severity.ERROR, "hidden text", evidence="=cmd|'/c calc'!A1")
    report.write_sheets(out, {"Reviews": [{"Title": "=HYPERLINK(\"http://example.org\",\"x\")"}]},
                        [("r1", finding)], [])
    assert _sheet(out, "Reviews").cell(row=2, column=1).data_type == "s"
    assert _sheet(out, "Review Findings").cell(row=2, column=6).data_type == "s"


def test_control_characters_that_an_excel_file_cannot_hold_are_dropped_from_the_review_report(tmp_path):
    out = tmp_path / "reviews.xlsx"
    finding = Finding("canary.hit", Severity.ERROR, "the review cites Garc\x0eia et al.", evidence="e\x0ecient\x00")
    report.write_sheets(out, {"Reviews": [{"Review": "An e\x0ecient tool"}]}, [("r1", finding)], [])
    assert _sheet(out, "Reviews").cell(row=2, column=1).value == "An ecient tool"
    assert [c.value for c in _sheet(out, "Review Findings")[2]][4:] == ["the review cites Garcia et al.", "ecient"]


def test_submission_sheet_with_a_control_character_in_a_title_extends_into_the_report(tmp_path):
    sheet = tmp_path / "submissions.csv"
    sheet.write_text("ID,Title\n7,Repair of\x0cBuild Scripts\n", encoding="utf-8")
    out = tmp_path / "report.xlsx"
    report.write_papers(out, _run(), profile.load("icse-2027"), sheet)
    assert _sheet(out, None).cell(row=2, column=2).value == "Repair ofBuild Scripts"


def test_files_without_a_paper_number_get_their_own_sheet(tmp_path):
    out = tmp_path / "report.xlsx"
    report.write_papers(out, _run(), profile.load("icse-2027"))
    rows = list(_sheet(out, "Files").iter_rows(min_row=2, values_only=True))
    assert [row[0] for row in rows] == ["odd name.pdf"] and "paper 10" in rows[0][1]


def test_json_report_holds_plain_values(tmp_path):
    out = tmp_path / "r.json"
    report.write_json(out, _run())
    data = json.loads(out.read_text())
    assert data["results"][0]["findings"][0]["severity"] == "error"
    assert data["results"][0]["paper"]["pdf"] == "CONF_2026_paper_7.pdf"


def test_json_report_goes_into_a_folder_that_does_not_exist_yet(tmp_path):
    out = tmp_path / "new" / "r.json"
    report.write_json(out, _run())
    assert json.loads(out.read_text(encoding="utf-8"))["numbered"] == {"10": "odd name.pdf"}


def test_json_report_keeps_a_file_name_that_is_not_valid_utf8(tmp_path):
    out = tmp_path / "r.json"
    run = _run()
    # Python reads the byte 0xE9 of a Latin-1 file name as the lone surrogate U+DCE9.
    run.numbered[11] = "caf\udce9.pdf"
    report.write_json(out, run)
    assert json.loads(out.read_text(encoding="utf-8"))["numbered"] == {"10": "odd name.pdf", "11": "caf\udce9.pdf"}


def test_html_page_escapes_text_from_pdfs_and_loads_nothing_from_the_web(tmp_path):
    out = tmp_path / "report.html"
    run = _run()
    run.results[0].findings.append(Finding("hidden-text.white-text", Severity.ERROR, "hidden text",
                                           evidence="<script>alert(1)</script>"))
    report.write_papers_html(out, run)
    page = out.read_text()
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page and "<script>alert(1)" not in page
    assert 'src="http' not in page and 'href="http' not in page
    assert "2 rows, 2 need review" in page


def test_html_page_of_reviews_lists_each_review_with_its_findings(tmp_path):
    out = tmp_path / "reviews.html"
    finding = Finding("duplicates.near-duplicate", Severity.WARNING, "paragraph also in review r2")
    report.write_rows_html(out, "PeerCheck, Reviews", [{"Review ID": "r1"}, {"Review ID": "r2"}], {"r1": [finding]},
                           "Review ID")
    page = out.read_text()
    assert "paragraph also in review r2" in page and "2 rows, 1 need review" in page


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
    rows = [{"Source File": "review_0007_1.xml", "Review ID": "r1", "Title": "A Secret Title", "Confidence": None}]
    report.write_rows_html(out, "PeerCheck, Reviews", rows, {}, "Review ID")
    page = out.read_text()
    assert "review_0007_1.xml" not in page and "A Secret Title" not in page and "Confidence" not in page


def test_html_page_leaves_out_the_columns_it_is_given(tmp_path):
    out = tmp_path / "reviews.html"
    rows = [{"Review ID": "r1", "CoCoDet Verdict": "AI", "Content Sources": "gpt4o"}]
    report.write_rows_html(out, "PeerCheck, Reviews", rows, {}, "Review ID", ("Content Sources",))
    page = out.read_text()
    assert "CoCoDet Verdict" in page and "Content Sources" not in page and "gpt4o" not in page

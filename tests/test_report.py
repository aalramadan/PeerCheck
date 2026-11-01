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
    results = [PaperResult(Paper(7, Path("ICSME_2026_paper_7.pdf")),
                           findings=[Finding("layout.main-pages", Severity.ERROR, "11 pages of main text, limit 10")]),
               PaperResult(Paper(9, Path("ICSME_2026_paper_9.pdf")),
                           findings=[Finding("input.not-in-sheet", Severity.WARNING,
                                             "PDF has no row in the submission sheet")])]
    return PapersRun(results, {}, ["odd name.pdf"], [], ("layout",))


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
    report.write_papers(out, _run(), profile.load("icsme-2026"), _submissions(tmp_path))
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


def test_unmatched_files_get_their_own_sheet(tmp_path):
    out = tmp_path / "report.xlsx"
    report.write_papers(out, _run(), profile.load("icsme-2026"))
    assert [row[0] for row in _sheet(out, "Files").iter_rows(min_row=2, values_only=True)] == ["odd name.pdf"]


def test_json_report_holds_plain_values(tmp_path):
    out = tmp_path / "r.json"
    report.write_json(out, _run())
    data = json.loads(out.read_text())
    assert data["results"][0]["findings"][0]["severity"] == "error"
    assert data["results"][0]["paper"]["pdf"] == "ICSME_2026_paper_7.pdf"

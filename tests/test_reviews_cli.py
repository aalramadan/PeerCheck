"""Tests of the review command line: the findings of each detector, and the canary column."""

from pathlib import Path
from types import SimpleNamespace

import openpyxl
import pytest

from peercheck import canary
from peercheck.findings import Finding, Severity

pytest.importorskip("torch")
cli = pytest.importorskip("peercheck.reviews.cli")
editlens = pytest.importorskip("peercheck.reviews.editlens")

ALL = ("cocodet", "editlens")
EASYCHAIR = Path(__file__).parent / "fixtures" / "easychair"


def test_a_cocodet_label_ai_marks_the_review():
    found = cli._detector_findings(SimpleNamespace(label="ai", probabilities={"ai": 0.98}), None)
    assert [(f.check, f.severity) for f in found] == [("cocodet.ai", Severity.WARNING)]
    assert found[0].message == "CoCoDet labels the review as AI-generated"


def test_an_editlens_label_is_a_note_of_its_own():
    found = cli._detector_findings(None, editlens.Verdict("ai-edited", 0.42))
    assert [(f.check, f.severity) for f in found] == [("editlens.ai-edited", Severity.INFO)]
    assert found[0].message == "EditLens labels the review as AI-edited"


def test_each_detector_reports_its_own_result():
    found = cli._detector_findings(SimpleNamespace(label="ai", probabilities={"ai": 1.0}), editlens.Verdict("ai", 0.999))
    assert [(f.check, f.severity) for f in found] == [("cocodet.ai", Severity.WARNING), ("editlens.ai", Severity.INFO)]


def test_human_and_mix_labels_give_no_finding():
    assert cli._detector_findings(SimpleNamespace(label="mix", probabilities={}), editlens.Verdict("human", 0.05)) == []


def test_cocodet_and_editlens_run_by_default():
    assert cli.parser().parse_args(["reviews"]).detectors == "cocodet,editlens"


def test_canary_column_names_the_state_of_the_review():
    assert cli._canary_state([Finding("canary.untested", Severity.INFO, "left out")]) == "untested"
    assert cli._canary_state([]) == "no"


def test_canary_check_runs_without_any_model_and_fills_its_column(tmp_path):
    key, out = tmp_path / "key.csv", tmp_path / "reviews.xlsx"
    canary.write_key(key, {7: "Smith et al. (2019)"})
    assert cli.main([str(EASYCHAIR), "--detectors", "", "--checks", "", "--canaries", str(key),
                     "--out", str(out)]) == 0
    sheet = openpyxl.load_workbook(out).worksheets[0]
    header = [cell.value for cell in sheet[1]]
    assert {row[header.index("Canary")] for row in sheet.iter_rows(min_row=2, values_only=True)} == {"no"}


def test_review_check_reads_a_hotcrp_export_and_shows_its_overall_merit(tmp_path):
    out = tmp_path / "reviews.xlsx"
    export = Path(__file__).parent / "fixtures" / "hotcrp" / "reviews.csv"
    assert cli.main([str(export), "--detectors", "", "--checks", "", "--out", str(out)]) == 0
    sheet = openpyxl.load_workbook(out).worksheets[0]
    header = [cell.value for cell in sheet[1]]
    rows = list(sheet.iter_rows(min_row=2, values_only=True))
    assert [row[header.index("Review ID")] for row in rows] == ["12A", "12B"]
    assert [row[header.index("Overall Evaluation")] for row in rows] == ["3", "2"]


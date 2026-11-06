"""Tests of the review command line: the rule that joins the detector labels, and the canary column."""

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


def test_two_detectors_that_agree_flag_the_review():
    found = cli._detector_findings({"CoCoDet": "CoCoDet P(AI) 0.98", "EditLens": "EditLens score 0.9990"}, ALL)
    assert [(f.check, f.severity) for f in found] == [("detectors.agree-ai", Severity.WARNING)]
    assert found[0].message == "CoCoDet and EditLens agree that the review reads as machine-written"


def test_one_detector_alone_gives_a_note_that_names_the_other():
    found = cli._detector_findings({"EditLens": "EditLens score 0.9990"}, ALL)
    assert [(f.check, f.severity) for f in found] == [("detectors.editlens-ai", Severity.INFO)]
    assert found[0].message == "EditLens finds AI involvement in the review; CoCoDet does not"


def test_a_detector_that_runs_alone_says_so():
    found = cli._detector_findings({"CoCoDet": "CoCoDet P(AI) 0.98"}, ("cocodet",))
    assert found[0].message == "CoCoDet labels the review as AI; no second detector ran"


def test_cocodet_counts_its_ai_label_and_editlens_its_score_from_the_agreement_threshold():
    verdict = SimpleNamespace(label="ai", probabilities={"ai": 0.97})
    assert list(cli._ai_calls(verdict, editlens.Verdict("ai-edited", editlens.AGREE_FROM))) == ["CoCoDet", "EditLens"]
    assert cli._ai_calls(SimpleNamespace(label="mix", probabilities={}), editlens.Verdict("human", 0.05)) == {}


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


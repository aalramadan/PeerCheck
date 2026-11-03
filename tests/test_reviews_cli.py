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

ALL = ("cocodet", "binoculars", "editlens")
EASYCHAIR = Path(__file__).parent / "fixtures" / "easychair"


def test_two_detectors_that_agree_flag_the_review():
    found = cli._detector_findings({"CoCoDet": "CoCoDet P(AI) 0.98", "EditLens": "EditLens score 0.9990"}, ALL)
    assert [(f.check, f.severity) for f in found] == [("detectors.agree-ai", Severity.WARNING)]
    assert found[0].message == "CoCoDet and EditLens agree that the review reads as machine-written"


def test_one_detector_alone_gives_a_note_that_names_the_others():
    found = cli._detector_findings({"Binoculars": "Binoculars score 0.8000 below threshold 0.8536"}, ALL)
    assert [(f.check, f.severity) for f in found] == [("detectors.binoculars-ai", Severity.INFO)]
    assert found[0].message == "Binoculars labels the review as AI; CoCoDet and EditLens do not"


def test_a_detector_that_runs_alone_says_so():
    found = cli._detector_findings({"CoCoDet": "CoCoDet P(AI) 0.98"}, ("cocodet",))
    assert found[0].message == "CoCoDet labels the review as AI; no second detector ran"


def test_each_detector_counts_only_its_ai_label():
    verdict = SimpleNamespace(label="ai", probabilities={"ai": 0.97})
    second = SimpleNamespace(machine=False, score=0.9, threshold=0.8536)
    assert list(cli._ai_calls(verdict, second, editlens.Verdict("ai", 0.999))) == ["CoCoDet", "EditLens"]
    assert cli._ai_calls(None, None, editlens.Verdict("ai-edited", 0.5)) == {}


def test_editlens_runs_only_when_asked():
    assert cli.parser().parse_args(["reviews"]).detectors == "cocodet,binoculars"


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

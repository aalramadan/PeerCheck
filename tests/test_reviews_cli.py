"""Tests of the review command line: the findings of each detector, and the canary column."""

import json
from pathlib import Path
from types import SimpleNamespace

import openpyxl
import pytest

from peercheck import canary
from peercheck.findings import Finding, Severity
from peercheck.models import Review

pytest.importorskip("torch")
cli = pytest.importorskip("peercheck.reviews.cli")
editlens = pytest.importorskip("peercheck.reviews.editlens")

EASYCHAIR = Path(__file__).parent / "fixtures" / "easychair"


def _venue(tmp_path: Path, editlens_on: bool = False) -> str:
    """Write venue rules that turn the review checks off, and EditLens unless asked, which keeps a run free of models."""
    path = tmp_path / "venue.yaml"
    path.write_text("name: Test\nsource: https://example.org\nformat:\n  style: IEEE\n  paper_size: [792, 612]\n"
                    "  columns: 2\n  main_pages: 10\n  reference_pages: 2\nchecks:\n  cocodet: {enabled: false}\n"
                    f"  editlens: {{enabled: {str(editlens_on).lower()}}}\n"
                    "  duplicates: {enabled: false}\n  citations: {enabled: false}\n", encoding="utf-8")
    return str(path)


def _easychair_review(path: Path, review_id: str, paper: int, text: str) -> None:
    path.write_text(f"""<?xml version='1.0' encoding='utf-8'?>
<review id="{review_id}" submission="{paper}" title="Paper {paper}">
  <field id="f2" name="Detailed Review Comments for Authors"><text>{text}</text></field>
</review>
""", encoding="utf-8")


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


def test_cocodet_and_editlens_run_by_default_when_a_token_is_set(monkeypatch):
    monkeypatch.setattr(editlens, "has_token", lambda: True)
    assert cli._detectors(None) == (("cocodet", "editlens"), [])


def test_editlens_is_skipped_with_a_note_without_a_token(monkeypatch, capsys):
    monkeypatch.setattr(editlens, "has_token", lambda: False)
    detectors, notes = cli._detectors(None)
    assert detectors == ("cocodet",) and notes[0].startswith("EditLens skipped")
    assert "EditLens skipped" in capsys.readouterr().err


def test_the_venue_turns_a_detector_off(monkeypatch):
    monkeypatch.setattr(editlens, "has_token", lambda: True)
    venue = SimpleNamespace(options=lambda name: {"enabled": False} if name == "cocodet" else {})
    assert cli._detectors(venue) == (("editlens",), [])


def test_a_skipped_editlens_is_noted_in_the_report(tmp_path, monkeypatch):
    monkeypatch.setattr(editlens, "has_token", lambda: False)
    out = tmp_path / "reviews.xlsx"
    assert cli.main([str(EASYCHAIR), "--profile", _venue(tmp_path, editlens_on=True), "--out", str(out)]) == 0
    assert "EditLens skipped" in out.with_suffix(".html").read_text(encoding="utf-8")
    about = {row[0]: row[1] for row in openpyxl.load_workbook(out)["About"].iter_rows(values_only=True)}
    assert about["Skipped"].startswith("EditLens skipped") and about["Detectors"] == "none"


def test_words_for_authors_are_counted_as_editlens_counts_them():
    text = "本文研究了不稳定的测试，实验覆盖十二个项目。然而，基线方法不足。"
    assert cli._row(Review("r1", 7, "", "r1.xml", author_text=text))["Words for Authors"] == 4


def test_canary_column_names_the_state_of_the_review():
    assert cli._canary_state([Finding("canary.untested", Severity.INFO, "left out")]) == "untested"
    assert cli._canary_state([]) == "no"


def test_canary_check_runs_without_any_model_and_fills_its_column(tmp_path):
    key, out = tmp_path / "key.csv", tmp_path / "reviews.xlsx"
    canary.write_key(key, {7: "Smith et al. (2019)"})
    assert cli.main([str(EASYCHAIR), "--profile", _venue(tmp_path), "--canaries", str(key),
                     "--out", str(out)]) == 0
    sheet = openpyxl.load_workbook(out).worksheets[0]
    header = [cell.value for cell in sheet[1]]
    assert {row[header.index("Canary")] for row in sheet.iter_rows(min_row=2, values_only=True)} == {"no"}


def test_reviews_command_writes_the_html_page_beside_the_workbook_by_default(tmp_path):
    out = tmp_path / "reviews.xlsx"
    assert cli.main([str(EASYCHAIR), "--profile", _venue(tmp_path), "--out", str(out)]) == 0
    assert out.is_file() and out.with_suffix(".html").is_file()


def test_a_canary_key_without_any_reviewed_paper_is_reported(tmp_path, capsys):
    key, out = tmp_path / "key.csv", tmp_path / "reviews.xlsx"
    canary.write_key(key, {99: "Smith et al. (2019)"})
    assert cli.main([str(EASYCHAIR), "--profile", _venue(tmp_path), "--canaries", str(key),
                     "--out", str(out)]) == 0
    assert "the canary key holds none of the reviewed papers" in capsys.readouterr().err
    about = dict(openpyxl.load_workbook(out)["About"].iter_rows(values_only=True))
    assert about["Reviewed papers in the canary key"] == "0 of 1"


def test_reviews_that_share_an_id_keep_their_own_rows_and_canary_results(tmp_path, capsys):
    folder, key, out = tmp_path / "reviews", tmp_path / "key.csv", tmp_path / "reviews.json"
    folder.mkdir()
    _easychair_review(folder / "a.xml", "r1", 7, "Following Smith et al. (2019), this paper studies flaky tests.")
    _easychair_review(folder / "b.xml", "r1", 8, "A careful study of flaky tests.")
    canary.write_key(key, {7: "Smith et al. (2019)", 8: "Johnson et al. (2021)"})
    assert cli.main([str(folder), "--profile", _venue(tmp_path), "--canaries", str(key),
                     "--out", str(tmp_path / "reviews.xlsx"), "--json", str(out)]) == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert [(r["Review ID"], r["Submission"], r["Canary"]) for r in data["reviews"]] == [("r1", 7, "hit"),
                                                                                         ("r1#2", 8, "no")]
    assert [[f["check"] for f in data["findings"][rid]] for rid in ("r1", "r1#2")] == [
        ["input.repeated-id", "canary.hit"], ["input.repeated-id"]]
    assert "2 reviews share the ID r1" in capsys.readouterr().err


def test_review_check_reads_a_hotcrp_export_and_shows_its_overall_merit(tmp_path):
    out = tmp_path / "reviews.xlsx"
    export = Path(__file__).parent / "fixtures" / "hotcrp" / "reviews.csv"
    assert cli.main([str(export), "--profile", _venue(tmp_path), "--out", str(out)]) == 0
    sheet = openpyxl.load_workbook(out).worksheets[0]
    header = [cell.value for cell in sheet[1]]
    rows = list(sheet.iter_rows(min_row=2, values_only=True))
    assert [row[header.index("Review ID")] for row in rows] == ["12A", "12B"]
    assert [row[header.index("Overall Evaluation")] for row in rows] == ["3", "2"]


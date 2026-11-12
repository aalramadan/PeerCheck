"""Tests of the review command line: the findings of each detector, and the canary column."""

import csv
from pathlib import Path
from types import SimpleNamespace

import pytest

from peercheck import canary
from peercheck.findings import Finding, Severity
from peercheck.models import Review

pytest.importorskip("torch")
cli = pytest.importorskip("peercheck.reviews.cli")
editlens = pytest.importorskip("peercheck.reviews.editlens")

REVIEWS = Path(__file__).parent / "fixtures" / "easychair" / "reviews.csv"


def _venue(tmp_path: Path, editlens_on: bool = False, canary_on: bool = True) -> str:
    """Write a template whose only keys are the canary check and EditLens if asked, which keeps a run free of models."""
    path = tmp_path / "venue.yaml"
    path.write_text("name: Test\nsource: https://example.org\nformat:\n  style: IEEE\n  paper_size: [792, 612]\n"
                    "  columns: 2\n  main_pages: 10\n  reference_pages: 2\nchecks:\n"
                    + ("  canary:\n" if canary_on else "") + ("  editlens:\n" if editlens_on else ""), encoding="utf-8")
    return str(path)


def _rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _checks(row: dict) -> list[str]:
    """Return the check of each finding in the Findings column, such as canary.hit."""
    return [line.split()[1].rstrip(":") for line in row["Findings"].splitlines()]


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


def test_a_detector_whose_key_the_template_leaves_out_does_not_run(monkeypatch):
    monkeypatch.setattr(editlens, "has_token", lambda: True)
    venue = SimpleNamespace(runs=lambda name: name != "cocodet")
    assert cli._detectors(venue) == (("editlens",), [])


def test_a_skipped_editlens_is_noted_in_the_report(tmp_path, monkeypatch):
    monkeypatch.setattr(editlens, "has_token", lambda: False)
    out = tmp_path / "reviews.csv"
    assert cli.main([str(REVIEWS), "--template", _venue(tmp_path, editlens_on=True), "--out", str(out)]) == 0
    page = out.with_suffix(".html").read_text(encoding="utf-8")
    assert "EditLens skipped" in page and "Detectors: none." in page


def test_words_for_authors_are_counted_as_editlens_counts_them():
    text = "本文研究了不稳定的测试，实验覆盖十二个项目。然而，基线方法不足。"
    assert cli._row(Review("r1", 7, "", "r1.xml", author_text=text))["Words for Authors"] == 4


def test_canary_column_names_the_state_of_the_review():
    assert cli._canary_state([Finding("canary.untested", Severity.INFO, "left out")]) == "untested"
    assert cli._canary_state([]) == "no"


def test_canary_check_runs_without_any_model_and_fills_its_column(tmp_path):
    key, out = tmp_path / "key.csv", tmp_path / "reviews.csv"
    canary.write_key(key, {7: "Smith et al. (2019)"})
    assert cli.main([str(REVIEWS), "--template", _venue(tmp_path), "--canaries", str(key),
                     "--out", str(out)]) == 0
    assert {row["Canary"] for row in _rows(out)} == {"no"}


def test_canary_check_stays_off_while_the_template_leaves_out_its_key(tmp_path, capsys):
    key = tmp_path / "canaries.csv"
    canary.write_key(key, {7: "Smith et al. (2019)"})
    out = tmp_path / "reviews.csv"
    venue = _venue(tmp_path, canary_on=False)
    assert cli.main([str(REVIEWS), "--template", venue, "--canaries", str(key), "--out", str(out)]) == 0
    assert "The template turns off cocodet, editlens, duplicates, citations, canary." in capsys.readouterr().err
    assert "Canary" not in _rows(out)[0] and "Canary key" not in out.with_suffix(".html").read_text(encoding="utf-8")


def test_reviews_command_never_writes_its_report_over_the_reviews_file(tmp_path, capsys):
    reviews = tmp_path / "reviews.csv"
    reviews.write_bytes(REVIEWS.read_bytes())
    assert cli.main([str(reviews), "--template", _venue(tmp_path), "--out", str(reviews)]) == 2
    assert "would overwrite the input" in capsys.readouterr().err
    assert reviews.read_bytes() == REVIEWS.read_bytes()


def test_reviews_command_writes_reviews_report_csv_by_default(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert cli.main([str(REVIEWS), "--template", _venue(tmp_path)]) == 0
    assert (tmp_path / "reviews-report.csv").is_file() and (tmp_path / "reviews-report.html").is_file()


def test_reviews_command_writes_the_html_page_beside_the_csv_file(tmp_path):
    out = tmp_path / "reviews.csv"
    assert cli.main([str(REVIEWS), "--template", _venue(tmp_path), "--out", str(out)]) == 0
    assert out.is_file() and out.with_suffix(".html").is_file()


def test_a_canary_key_without_any_reviewed_paper_is_reported(tmp_path, capsys):
    key, out = tmp_path / "key.csv", tmp_path / "reviews.csv"
    canary.write_key(key, {99: "Smith et al. (2019)"})
    assert cli.main([str(REVIEWS), "--template", _venue(tmp_path), "--canaries", str(key),
                     "--out", str(out)]) == 0
    assert "the canary key holds none of the reviewed papers" in capsys.readouterr().err
    assert "which holds 0 of 1 reviewed papers" in out.with_suffix(".html").read_text(encoding="utf-8")


def test_reviews_that_share_an_id_keep_their_own_rows_and_canary_results(tmp_path, capsys):
    reviews, key, out = tmp_path / "reviews.csv", tmp_path / "key.csv", tmp_path / "report.csv"
    reviews.write_text("paper,review,Comments for authors\n"
                       "7,A,\"Following Smith et al. (2019), this paper studies flaky tests.\"\n"
                       "7,A,A careful study of flaky tests.\n", encoding="utf-8")
    canary.write_key(key, {7: "Smith et al. (2019)"})
    assert cli.main([str(reviews), "--template", _venue(tmp_path), "--canaries", str(key), "--out", str(out)]) == 0
    rows = _rows(out)
    assert [(r["Review ID"], r["Submission"], r["Canary"]) for r in rows] == [("7A", "7", "hit"), ("7A#2", "7", "no")]
    assert [_checks(r) for r in rows] == [["input.repeated-id", "canary.hit"], ["input.repeated-id"]]
    assert "2 reviews share the ID 7A" in capsys.readouterr().err


def test_review_check_reads_a_hotcrp_export_and_shows_its_overall_merit(tmp_path):
    out = tmp_path / "report.csv"
    export = Path(__file__).parent / "fixtures" / "hotcrp" / "reviews.csv"
    assert cli.main([str(export), "--template", _venue(tmp_path), "--out", str(out)]) == 0
    rows = _rows(out)
    assert [row["Review ID"] for row in rows] == ["12A", "12B"]
    assert [row["Overall Evaluation"] for row in rows] == ["3", "2"]


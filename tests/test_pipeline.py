"""Tests of the paper pipeline: which checks run under the keys of the template and the command line."""

import os
import shutil
import time
from pathlib import Path

import pytest
import yaml

from peercheck import profile, tools
from peercheck.findings import Finding, Severity
from peercheck.papers import layout, pipeline, sigsoft

FIXTURES = Path(__file__).parent / "fixtures"
HIDDEN = FIXTURES / "hidden"
# The checks of one paper as the module defines them, also where a test replaces the name in the module.
PAPER_CHECKS = pipeline._paper_checks


def _icse_without_hidden_text(tmp_path):
    data = yaml.safe_load((profile.PROFILES / "icse-2027.yaml").read_text())
    del data["checks"]["hidden_text"]
    path = tmp_path / "venue.yaml"
    path.write_text(yaml.safe_dump(data))
    return profile.load(str(path))


def test_every_paper_check_runs_under_the_default_template():
    assert pipeline.selected_checks(None, profile.load(profile.DEFAULT)) == pipeline.PAPER_CHECKS


def test_check_whose_key_the_template_leaves_out_runs_only_when_requested(tmp_path):
    venue = _icse_without_hidden_text(tmp_path)
    assert "hidden-text" not in pipeline.selected_checks(None, venue)
    assert pipeline.selected_checks(["hidden-text"], venue) == ("hidden-text",)


def test_numbered_and_skipped_pdfs_become_findings_of_their_papers(tmp_path):
    pdfs = tmp_path / "pdfs"
    pdfs.mkdir()
    for name in ("icse2027-paper1.pdf", "icse2027-paper1-copy.pdf", "notes.pdf"):
        shutil.copyfile(HIDDEN / "h01-white.pdf", pdfs / name)
    run = pipeline.run_papers(pdfs, profile.load("icse-2027"), checks=["hidden-text"])
    codes = {result.paper.paper_id: {f.check for f in result.findings} for result in run.results}
    assert "input.repeated-pdf" in codes[1] and "input.numbered" in codes[2]
    assert "input.numbered" not in codes[1] and "input.repeated-pdf" not in codes[2]


def test_requested_check_runs_although_the_template_leaves_out_its_key(tmp_path):
    pdfs = tmp_path / "pdfs"
    pdfs.mkdir()
    # h01-white hides an instruction to a model in white text.
    shutil.copyfile(HIDDEN / "h01-white.pdf", pdfs / "icse2027-paper1.pdf")
    run = pipeline.run_papers(pdfs, _icse_without_hidden_text(tmp_path), checks=["hidden-text"])
    assert run.checks == ("hidden-text",)
    assert ("hidden-text.white-text", Severity.ERROR) in {(f.check, f.severity) for f in run.results[0].findings}


def _run(tmp_path, monkeypatch, fixture, checks, banal_findings=()):
    """Run the pipeline on one fixture PDF with banal and the SIGSOFT jar replaced by fixed answers."""
    pdfs = tmp_path / "pdfs"
    pdfs.mkdir(parents=True)
    shutil.copyfile(FIXTURES / fixture, pdfs / "icse2027-paper1.pdf")
    monkeypatch.setattr(layout, "inspect", lambda paper, venue: layout.LayoutResult(None, list(banal_findings)))
    monkeypatch.setattr(sigsoft, "check_batch", lambda papers, venue, folder: {})
    run = pipeline.run_papers(pdfs, profile.load("icse-2027"), checks=checks)
    return {f.check for f in run.results[0].findings}


def test_format_check_runs_the_font_margin_integrity_and_unresolved_checks_of_peercheck(tmp_path, monkeypatch):
    assert "pdf.permissions" in _run(tmp_path, monkeypatch, "integrity/owner-password.pdf", ["layout"])
    assert "fonts.not-embedded" in _run(tmp_path / "b", monkeypatch, "fonts/ieee-unembedded.pdf", ["layout"])
    assert "margins.overflow" in _run(tmp_path / "c", monkeypatch, "margins/ieee-wide-table.pdf", ["layout"])


def test_anonymity_check_runs_the_identity_check_of_peercheck(tmp_path, monkeypatch):
    assert "identity.home-folder" in _run(tmp_path, monkeypatch, "identity/figure-author-home.pdf", ["sigsoft"])
    assert "identity.home-folder" not in _run(tmp_path / "b", monkeypatch, "identity/figure-author-home.pdf",
                                              ["layout"])


def test_pdf_that_needs_a_password_keeps_only_that_finding_of_its_errors(tmp_path, monkeypatch):
    banal = [Finding("layout.error", Severity.WARNING, "banal could not read the PDF")]
    failed = {1: [Finding("references.error", Severity.WARNING, "The reference check did not run")]}
    monkeypatch.setattr(pipeline.references, "check_batch", lambda papers, venue, folder: failed)
    codes = _run(tmp_path, monkeypatch, "integrity/user-password.pdf", ["layout", "hidden-text", "references"], banal)
    assert "pdf.password" in codes
    assert not {code for code in codes if code.endswith(".error")}


def test_format_check_that_raises_is_reported_for_its_paper_and_leaves_the_other_checks_running(tmp_path, monkeypatch):
    def raising(paper, venue):
        raise AttributeError("made-up failure")

    pdfs = tmp_path / "pdfs"
    pdfs.mkdir()
    shutil.copyfile(HIDDEN / "h01-white.pdf", pdfs / "icse2027-paper1.pdf")
    monkeypatch.setattr(layout, "inspect", raising)
    run = pipeline.run_papers(pdfs, profile.load("icse-2027"), checks=["layout", "hidden-text"])
    found = {f.check: f.message for f in run.results[0].findings}
    assert found["layout.error"] == "AttributeError: made-up failure"
    assert "hidden-text.white-text" in found


def test_findings_of_a_paper_stand_in_the_order_format_input_anonymity_other_checks_and_references(tmp_path,
                                                                                                 monkeypatch):
    pdfs = tmp_path / "pdfs"
    pdfs.mkdir()
    shutil.copyfile(HIDDEN / "h01-white.pdf", pdfs / "notes.pdf")
    note = lambda code: [Finding(code, Severity.INFO, "made-up")]
    monkeypatch.setattr(layout, "inspect", lambda paper, venue: layout.LayoutResult(None, note("layout.made-up")))
    monkeypatch.setattr(sigsoft, "check_batch", lambda papers, venue, folder: {1: note("sigsoft.made-up")})
    monkeypatch.setattr(pipeline.references, "check_batch", lambda papers, venue, folder: {1: note("references.x")})
    monkeypatch.setattr(pipeline, "COMPANION_CHECKS", {})
    checks = ["references", "hidden-text", "sigsoft", "layout"]
    run = pipeline.run_papers(pdfs, profile.load("icse-2027"), checks=checks)
    codes = [f.check for f in run.results[0].findings]
    assert codes[:3] == ["layout.made-up", "input.numbered", "sigsoft.made-up"]
    assert codes[3].startswith("hidden-text.") and codes[-1] == "references.x"


def test_progress_names_each_paper_with_its_errors_and_warnings_after_the_note_on_the_references(tmp_path, monkeypatch,
                                                                                                capsys):
    found = [Finding("references.retracted", Severity.ERROR, "made-up"),
             Finding("references.not-found", Severity.WARNING, "made-up"),
             Finding("references.not-found", Severity.WARNING, "made-up"),
             Finding("references.summary", Severity.INFO, "made-up")]
    monkeypatch.setattr(pipeline.references, "check_batch", lambda papers, venue, folder: {1: found, 2: found[1:2]})
    pipeline.run_papers(_hidden_text_papers(tmp_path, "h01-white.pdf", "h01-white.pdf"), profile.load("icse-2027"),
                        checks=["references"])
    assert capsys.readouterr().err.splitlines() == [
        "Looking up the references of 2 papers.",
        "[1/2] paper 1: 1 error(s), 2 warning(s)",
        "[2/2] paper 2: 0 error(s), 1 warning(s)"]


def test_format_check_runs_the_image_check_of_peercheck(tmp_path, monkeypatch):
    assert "images.low-resolution" in _run(tmp_path, monkeypatch, "images/low-resolution.pdf", ["layout"])


def test_hidden_text_check_runs_the_active_content_check_and_reports_each_script_once(tmp_path, monkeypatch):
    codes = _run(tmp_path, monkeypatch, "active/javascript-animation.pdf", ["hidden-text"])
    assert "active-content.javascript" in codes and "hidden-text.javascript" not in codes


def test_format_check_compares_the_density_of_each_paper_with_the_whole_batch(tmp_path, monkeypatch):
    batches = []

    def check_batch(measures, venue):
        batches.append(sorted(measures))
        return {paper_id: [Finding("density.characters", Severity.WARNING, "dense")] for paper_id in measures}

    monkeypatch.setattr(pipeline.density, "measure", lambda paper, measured: paper.paper_id)
    monkeypatch.setattr(pipeline.density, "check_batch", check_batch)
    assert "density.characters" in _run(tmp_path, monkeypatch, "images/clean.pdf", ["layout"])
    assert batches == [[1]]
    assert "density.characters" not in _run(tmp_path / "b", monkeypatch, "images/clean.pdf", ["hidden-text"])


def _hidden_text_papers(tmp_path, *fixtures):
    pdfs = tmp_path / "pdfs"
    pdfs.mkdir(parents=True)
    for number, fixture in enumerate(fixtures, start=1):
        shutil.copyfile(HIDDEN / fixture, pdfs / f"icse2027-paper{number}.pdf")
    return pdfs


def _ending_its_process_on_paper_2(paper, venue, names, folder):
    if paper.paper_id == 2:
        os._exit(1)
    return PAPER_CHECKS(paper, venue, names, folder)


def _never_returning(paper, venue, names, folder):
    time.sleep(600)


def _codes(result):
    return sorted((f.check, f.message) for f in result.findings)


def test_each_paper_gets_the_findings_of_its_own_pdf_when_several_are_checked_at_the_same_time(tmp_path, monkeypatch):
    fixtures = ("h01-white.pdf", "h04-tiny-05pt.pdf", "h10-off-page.pdf")
    venue = profile.load("icse-2027")
    alone = [_codes(pipeline.run_papers(_hidden_text_papers(tmp_path / fixture, fixture), venue,
                                        checks=["hidden-text"]).results[0]) for fixture in fixtures]
    monkeypatch.setattr(pipeline, "WORKERS", 2)
    together = pipeline.run_papers(_hidden_text_papers(tmp_path / "all", *fixtures), venue, checks=["hidden-text"])
    assert [_codes(result) for result in together.results] == alone
    assert len({tuple(codes) for codes in alone}) == 3


def test_paper_that_ends_its_process_goes_without_its_checks_while_the_other_papers_are_checked(tmp_path, monkeypatch):
    pdfs = _hidden_text_papers(tmp_path, "h01-white.pdf", "h01-white.pdf", "h01-white.pdf")
    monkeypatch.setattr(pipeline, "WORKERS", 2)
    monkeypatch.setattr(pipeline, "_paper_checks", _ending_its_process_on_paper_2)
    run = pipeline.run_papers(pdfs, profile.load("icse-2027"), checks=["hidden-text"])
    codes = [{f.check for f in result.findings} for result in run.results]
    assert [(f.check, f.message) for f in run.results[1].findings] == [
        ("pdf.error", "the checks stopped while they read the PDF")]
    assert "hidden-text.white-text" in codes[0] and "hidden-text.white-text" in codes[2]


def test_check_of_all_papers_that_fails_stops_the_run_at_once(tmp_path, monkeypatch):
    def failing(papers, venue, folder):
        raise tools.ToolError("java not found")

    pdfs = _hidden_text_papers(tmp_path, "h01-white.pdf", "h01-white.pdf", "h01-white.pdf")
    monkeypatch.setattr(pipeline, "WORKERS", 2)
    monkeypatch.setattr(pipeline, "_paper_checks", _never_returning)
    monkeypatch.setattr(sigsoft, "check_batch", failing)
    start = time.monotonic()
    with pytest.raises(tools.ToolError, match="java not found"):
        pipeline.run_papers(pdfs, profile.load("icse-2027"), checks=["sigsoft", "hidden-text"])
    assert time.monotonic() - start < 120


def test_papers_go_to_their_checks_before_the_checks_that_take_all_papers_in_one_run(tmp_path, monkeypatch):
    events = []

    class Recorded(pipeline._SameProcess):
        def submit(self, fn, /, *args, **kwargs):
            events.append("paper")
            return super().submit(fn, *args, **kwargs)

    monkeypatch.setattr(pipeline, "_pool", lambda papers: Recorded())
    monkeypatch.setattr(sigsoft, "check_batch", lambda papers, venue, folder: events.append("anonymity") or {})
    monkeypatch.setattr(pipeline.references, "check_batch",
                        lambda papers, venue, folder: events.append("lookups") or {})
    pipeline.run_papers(_hidden_text_papers(tmp_path, "h01-white.pdf", "h01-white.pdf"), profile.load("icse-2027"),
                        checks=["references", "sigsoft"])
    assert events == ["paper", "paper", "anonymity", "lookups"]


def test_several_papers_run_in_at_most_eight_processes_and_a_single_paper_in_this_process(monkeypatch):
    assert 1 <= pipeline.WORKERS <= 8
    monkeypatch.setattr(pipeline, "PaperProcesses", lambda workers, seconds: (workers, seconds))
    monkeypatch.setattr(pipeline, "WORKERS", 4)
    assert pipeline._pool(9) == (4, pipeline.PAPER_SECONDS) and pipeline._pool(3) == (3, pipeline.PAPER_SECONDS)
    assert isinstance(pipeline._pool(1), pipeline._SameProcess)
    monkeypatch.setattr(pipeline, "WORKERS", 1)
    assert isinstance(pipeline._pool(9), pipeline._SameProcess)


def test_references_of_all_papers_are_looked_up_in_one_run_after_the_other_findings(tmp_path, monkeypatch):
    pdfs = _hidden_text_papers(tmp_path, "h01-white.pdf", "h01-white.pdf")
    batches = []

    def check_batch(papers, venue, folder):
        batches.append([paper.paper_id for paper in papers])
        return {paper.paper_id: [Finding("references.summary", Severity.INFO, "looked up")] for paper in papers}

    monkeypatch.setattr(pipeline.references, "check_batch", check_batch)
    run = pipeline.run_papers(pdfs, profile.load("icse-2027"), checks=["references", "hidden-text"])
    assert batches == [[1, 2]]
    assert [result.findings[-1].check for result in run.results] == ["references.summary"] * 2
    assert all("hidden-text.white-text" in {f.check for f in result.findings} for result in run.results)


def test_reference_check_that_fails_is_reported_for_each_paper(tmp_path, monkeypatch):
    def check_batch(papers, venue, folder):
        raise RuntimeError("made-up failure")

    monkeypatch.setattr(pipeline.references, "check_batch", check_batch)
    run = pipeline.run_papers(_hidden_text_papers(tmp_path, "h01-white.pdf", "h01-white.pdf"),
                              profile.load("icse-2027"), checks=["references"])
    assert [[(f.check, f.message) for f in result.findings] for result in run.results] == [
        [("references.error", "RuntimeError: made-up failure")]] * 2

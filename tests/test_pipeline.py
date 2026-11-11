"""Tests of the paper pipeline: which checks run under the switches of the profile and the command line."""

import shutil
from pathlib import Path

import yaml

from peercheck import profile
from peercheck.findings import Finding, Severity
from peercheck.papers import layout, pipeline, sigsoft

FIXTURES = Path(__file__).parent / "fixtures"
HIDDEN = FIXTURES / "hidden"


def _icse_with_hidden_text(tmp_path, options):
    data = yaml.safe_load((profile.PROFILES / "icse-2027.yaml").read_text())
    data["checks"]["hidden_text"] = options
    path = tmp_path / "venue.yaml"
    path.write_text(yaml.safe_dump(data))
    return profile.load(str(path))


def test_check_that_the_profile_turns_off_runs_only_when_requested(tmp_path):
    venue = _icse_with_hidden_text(tmp_path, False)
    assert "hidden-text" not in pipeline.selected_checks(None, venue)
    assert pipeline.selected_checks(["hidden-text"], venue) == ("hidden-text",)


def test_requested_check_runs_although_the_profile_turns_it_off(tmp_path):
    pdfs = tmp_path / "pdfs"
    pdfs.mkdir()
    # h01-white hides an instruction to a model in white text.
    shutil.copyfile(HIDDEN / "h01-white.pdf", pdfs / "icse2027-paper1.pdf")
    run = pipeline.run_papers(pdfs, _icse_with_hidden_text(tmp_path, {"enabled": False}), checks=["hidden-text"])
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
    codes = _run(tmp_path, monkeypatch, "integrity/user-password.pdf", ["layout", "hidden-text"], banal)
    assert "pdf.password" in codes
    assert not {code for code in codes if code.endswith(".error")}


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

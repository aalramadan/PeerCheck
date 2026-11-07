"""Tests of the paper pipeline: which checks run under the switches of the profile and the command line."""

import shutil
from pathlib import Path

import yaml

from peercheck import pipeline, profile
from peercheck.findings import Severity

HIDDEN = Path(__file__).parent / "fixtures" / "hidden"


def _icse_with_hidden_text(tmp_path, options):
    data = yaml.safe_load((profile.resources.files("peercheck") / "profiles" / "icse-2027.yaml").read_text())
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

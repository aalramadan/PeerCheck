"""Tests of the command line of PeerCheck."""
from peercheck import cli


def test_command_line_applies_the_icse_2027_profile_by_default():
    assert cli.parser().parse_args(["papers", "pdfs"]).profile == "icse-2027"


def _review_command(monkeypatch, argv):
    """Run the reviews command and return the command line that it hands to the review checks."""
    calls = []
    monkeypatch.setattr(cli.importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(cli.subprocess, "call", lambda command: calls.append(command) or 0)
    assert cli.main(argv) == 0
    return calls[0][3:]


def test_reviews_command_hands_help_to_the_review_checks(monkeypatch):
    assert _review_command(monkeypatch, ["reviews", "--help"]) == ["--profile", "icse-2027", "--help"]


def test_reviews_command_keeps_an_option_that_comes_before_the_folder(monkeypatch):
    argv = ["--profile", "fse-2027", "reviews", "--canaries", "key.csv", "exports"]
    assert _review_command(monkeypatch, argv) == ["--profile", "fse-2027", "--canaries", "key.csv", "exports"]

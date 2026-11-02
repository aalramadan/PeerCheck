"""Tests of the command line of PeerCheck."""
from peercheck import cli


def test_command_line_applies_the_icse_2027_profile_by_default():
    assert cli.parser().parse_args(["papers", "pdfs"]).profile == "icse-2027"

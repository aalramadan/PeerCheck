"""Tests of loading and validating venue profiles."""

import pytest
import yaml

from peercheck import profile


def _shipped(key):
    return yaml.safe_load((profile.resources.files("peercheck") / "profiles" / f"{key}.yaml").read_text())


def test_shipped_profiles_load():
    assert profile.available() == ["fse-2027", "icse-2027", "icsme-2026"]
    for key in profile.available():
        assert profile.load(key).key == key


def test_icsme_profile_states_the_page_rule_of_the_call():
    rules = profile.load("icsme-2026").format
    assert (rules.main_pages, rules.reference_pages, rules.columns) == (10, 2, 2)
    assert rules.paper_size == (792.0, 612.0)


def test_paper_id_matches_easychair_names_in_any_case():
    venue = profile.load("icsme-2026")
    assert venue.paper_id("ICSME_2026_paper_0108.pdf") == 108
    assert venue.paper_id("icsme_2026_PAPER_12.PDF") == 12
    assert venue.paper_id("ICSME_2026_paper_0041 (1).pdf") is None


def test_paper_id_matches_hotcrp_names():
    assert profile.load("icse-2027").paper_id("icse2027-paper123.pdf") == 123


def test_unknown_profile_names_the_shipped_ones():
    with pytest.raises(profile.ProfileError, match="icsme-2026"):
        profile.load("no-such-venue")


def test_profile_file_with_an_unknown_key_is_rejected(tmp_path):
    data = _shipped("icsme-2026")
    data["format"]["page_limit"] = 10
    path = tmp_path / "venue.yaml"
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(profile.ProfileError, match="page_limit"):
        profile.load(str(path))


def test_file_pattern_needs_one_group(tmp_path):
    data = _shipped("icsme-2026")
    data["file_pattern"] = r"paper\d+\.pdf"
    path = tmp_path / "venue.yaml"
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(profile.ProfileError, match="one group"):
        profile.load(str(path))


def test_options_of_an_unset_check_are_empty():
    assert profile.load("icsme-2026").options("no-such-check") == {}

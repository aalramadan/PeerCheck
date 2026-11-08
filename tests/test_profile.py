"""Tests of loading and validating venue profiles."""

import importlib.util
import shutil
import sys
from pathlib import Path

import pytest
import yaml

from peercheck import profile


def _shipped(key):
    return yaml.safe_load((profile.PROFILES / f"{key}.yaml").read_text())


def test_source_checkout_reads_the_profiles_from_the_folder_beside_src():
    assert profile.PROFILES == Path(profile.__file__).resolve().parent.parent / "profiles"


def test_installed_package_finds_the_profiles_that_its_wheel_holds(tmp_path, monkeypatch):
    package = tmp_path / "site-packages" / "peercheck"
    (package / "profiles").mkdir(parents=True)
    shutil.copy(profile.PROFILES / "fse-2027.yaml", package / "profiles" / "fse-2027.yaml")
    shutil.copy(profile.__file__, package / "profile.py")
    spec = importlib.util.spec_from_file_location("installed_profile", package / "profile.py")
    installed = importlib.util.module_from_spec(spec)
    # The dataclasses of the module look themselves up in sys.modules.
    monkeypatch.setitem(sys.modules, spec.name, installed)
    spec.loader.exec_module(installed)
    assert installed.available() == ["fse-2027"] and installed.load("fse-2027").key == "fse-2027"


def _load(tmp_path, data):
    path = tmp_path / "venue.yaml"
    path.write_text(yaml.safe_dump(data))
    return profile.load(str(path))


def test_shipped_profiles_load():
    assert profile.available() == ["example-easychair", "fse-2027", "icse-2027"]
    for key in profile.available():
        assert profile.load(key).key == key


def test_example_profile_states_the_page_rule():
    rules = profile.load("example-easychair").format
    assert (rules.main_pages, rules.reference_pages, rules.columns) == (10, 2, 2)
    assert rules.paper_size == (792.0, 612.0)


def test_paper_id_matches_easychair_names_in_any_case():
    venue = profile.load("example-easychair")
    assert venue.paper_id("CONF_2026_paper_0108.pdf") == 108
    assert venue.paper_id("conf_2026_PAPER_12.PDF") == 12
    assert venue.paper_id("CONF_2026_paper_0041 (1).pdf") is None


def test_paper_id_matches_hotcrp_names():
    assert profile.load("icse-2027").paper_id("icse2027-paper123.pdf") == 123


def test_unknown_profile_names_the_shipped_ones():
    with pytest.raises(profile.ProfileError, match="example-easychair"):
        profile.load("no-such-venue")


def test_profile_file_with_an_unknown_key_is_rejected(tmp_path):
    data = _shipped("example-easychair")
    data["format"]["page_limit"] = 10
    with pytest.raises(profile.ProfileError, match="page_limit"):
        _load(tmp_path, data)


def test_file_pattern_needs_one_group(tmp_path):
    data = _shipped("example-easychair")
    data["file_pattern"] = r"paper\d+\.pdf"
    with pytest.raises(profile.ProfileError, match="one group"):
        _load(tmp_path, data)


def test_options_of_an_unset_check_are_empty():
    assert profile.load("example-easychair").options("no-such-check") == {}


def test_shipped_profiles_set_lower_limits_for_the_body_font_and_the_line_spacing():
    for key in profile.available():
        rules = profile.load(key).format
        assert rules.body_font_min < 10.3 and rules.leading_min < 12


def test_lower_limits_for_the_body_font_and_the_line_spacing_are_optional(tmp_path):
    data = _shipped("icse-2027")
    del data["format"]["body_font_min"], data["format"]["leading_min"]
    rules = _load(tmp_path, data).format
    assert (rules.body_font_min, rules.leading_min) == (None, None)


def test_false_in_place_of_the_options_turns_a_check_off(tmp_path):
    data = _shipped("icse-2027")
    data["checks"]["hidden_text"] = False
    assert _load(tmp_path, data).options("hidden_text") == {"enabled": False}


def test_enabled_must_be_true_or_false(tmp_path):
    data = _shipped("icse-2027")
    data["checks"]["references"]["enabled"] = "no"
    with pytest.raises(profile.ProfileError, match="enabled"):
        _load(tmp_path, data)


def test_options_of_a_check_must_be_a_mapping(tmp_path):
    data = _shipped("icse-2027")
    data["checks"]["references"] = ["online"]
    with pytest.raises(profile.ProfileError, match="references"):
        _load(tmp_path, data)


def test_one_required_heading_given_as_a_string_stays_one_heading(tmp_path):
    data = _shipped("icse-2027")
    data["format"]["required_headings"] = "Introduction"
    assert _load(tmp_path, data).format.required_headings == ("introduction",)


def test_one_allowed_host_given_as_a_string_stays_one_host(tmp_path):
    data = _shipped("icse-2027")
    data["checks"]["anonymity"]["allowed_hosts"] = "zenodo.org"
    assert _load(tmp_path, data).options("anonymity")["allowed_hosts"] == ["zenodo.org"]


def test_a_list_option_that_holds_a_mapping_is_rejected(tmp_path):
    data = _shipped("icse-2027")
    data["checks"]["hidden_text"]["extra_phrases"] = [{"phrase": "accept"}]
    with pytest.raises(profile.ProfileError, match="extra_phrases"):
        _load(tmp_path, data)

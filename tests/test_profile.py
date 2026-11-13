"""Tests of loading and validating templates."""

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
    assert profile.PROFILES == Path(profile.__file__).resolve().parent.parent / "templates"


def test_installed_package_finds_the_templates_that_its_wheel_holds(tmp_path, monkeypatch):
    package = tmp_path / "site-packages" / "peercheck"
    (package / "templates").mkdir(parents=True)
    shutil.copy(profile.PROFILES / "fse-2027.yaml", package / "templates" / "fse-2027.yaml")
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
    assert profile.available() == ["fse-2027", "icse-2027"]
    for key in profile.available():
        assert profile.load(key).key == key


def test_example_profile_states_the_page_rule():
    rules = profile.load("icse-2027").format
    assert (rules.main_pages, rules.reference_pages, rules.columns) == (10, 2, 2)
    assert rules.paper_size == (792.0, 612.0)


@pytest.mark.parametrize(("name", "number"), [
    ("CONF_2026_paper_0108.pdf", 108), ("conf_2026_PAPER_12.PDF", 12), ("CONF_2026_paper_0041 (1).pdf", 41),
    ("CONF27_paper__11.pdf", 11), ("icse2027-paper123.pdf", 123), ("submission-9.pdf", 9), ("12.pdf", 12),
    ("Smith2025.pdf", None), ("notes.pdf", None)])
def test_paper_number_comes_from_the_names_that_submission_systems_give(name, number):
    assert profile.paper_number(name) == number


def test_file_pattern_of_a_profile_reads_names_of_another_form(tmp_path):
    data = _shipped("icse-2027")
    data["file_pattern"] = r"sub-(\d+)\.pdf$"
    assert _load(tmp_path, data).paper_id("sub-7.pdf") == 7


def test_default_rules_load_and_stay_out_of_the_examples():
    rules = profile.load(profile.DEFAULT).format
    assert (rules.style, rules.columns, rules.main_pages, rules.reference_pages) == ("IEEE", 2, 10, 2)
    assert profile.DEFAULT not in profile.available()


def test_profile_without_values_names_the_default_file(tmp_path):
    empty = tmp_path / "venue.yaml"
    empty.write_text("# only comments\n", encoding="utf-8")
    with pytest.raises(profile.ProfileError, match="copy templates/default.yaml"):
        profile.load(str(empty))


def test_the_required_lines_alone_make_a_profile(tmp_path):
    data = {"name": "A venue", "source": "https://example.org", "format": {
        "style": "ACM", "paper_size": [792, 612], "columns": 2, "main_pages": 10, "reference_pages": 2}}
    rules = _load(tmp_path, data).format
    assert (rules.page_numbers, rules.paper_size_tolerance, rules.body_font_max, rules.required_headings) == (
        "ignore", 5.0, None, ())


def test_profile_without_a_page_limit_is_rejected(tmp_path):
    data = {"name": "A venue", "source": "https://example.org", "format": {
        "style": "ACM", "paper_size": [792, 612], "columns": 2, "reference_pages": 2}}
    with pytest.raises(profile.ProfileError, match="main_pages"):
        _load(tmp_path, data)


def test_unknown_profile_names_the_shipped_ones():
    with pytest.raises(profile.ProfileError, match="icse-2027"):
        profile.load("no-such-venue")


def test_template_file_that_does_not_exist_is_named_as_a_missing_file(tmp_path):
    with pytest.raises(profile.ProfileError, match="template file not found: .*venue.yaml"):
        profile.load(str(tmp_path / "venue.yaml"))


@pytest.mark.parametrize("name", ["icse-2027.yaml", "templates/icse-2027.yaml"])
def test_shipped_template_named_as_a_file_that_does_not_exist_gets_the_shipped_keys(tmp_path, monkeypatch, name):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(profile.ProfileError,
                       match=f"template file not found: {name}; shipped templates: fse-2027, icse-2027"):
        profile.load(name)


def test_template_file_that_is_no_yaml_is_rejected_with_the_line_of_the_mistake(tmp_path):
    path = tmp_path / "venue.yaml"
    path.write_text("name: A venue\nformat:\n\tstyle: IEEE\n", encoding="utf-8")
    with pytest.raises(profile.ProfileError, match="template venue: line 3 is no valid YAML") as caught:
        profile.load(str(path))
    assert caught.value.__cause__.problem in str(caught.value)


def test_template_file_with_a_yaml_mistake_that_has_no_line_is_rejected_as_a_file(tmp_path):
    path = tmp_path / "venue.yaml"
    path.write_text('name: "A\x01venue"\n', encoding="utf-8")
    with pytest.raises(profile.ProfileError, match="template venue: the file is no valid YAML"):
        profile.load(str(path))


@pytest.mark.parametrize(("name", "value"), [
    ("columns", "two"), ("main_pages", [10]), ("main_pages", None), ("reference_pages", float("inf")),
    ("body_font_max", "large"), ("margins", [52, 48, "wide", 48]), ("margins", [52, 48, [1], 48])])
def test_format_rule_that_is_no_number_is_rejected_with_its_name(tmp_path, name, value):
    data = _shipped("icse-2027")
    data["format"][name] = value
    with pytest.raises(profile.ProfileError, match=f"template venue: {name} must"):
        _load(tmp_path, data)


def test_format_rule_set_to_nothing_takes_its_default(tmp_path):
    data = _shipped("icse-2027")
    data["format"].update(paper_size_tolerance=None, margin_tolerance=None, body_font_max=None)
    rules = _load(tmp_path, data).format
    assert (rules.paper_size_tolerance, rules.margin_tolerance, rules.body_font_max) == (5.0, 18.0, None)


def test_profile_file_with_an_unknown_key_is_rejected(tmp_path):
    data = _shipped("icse-2027")
    data["format"]["page_limit"] = 10
    with pytest.raises(profile.ProfileError, match="page_limit"):
        _load(tmp_path, data)


def test_profile_file_with_a_number_as_a_key_is_rejected_with_the_key(tmp_path):
    data = _shipped("icse-2027")
    data["format"][7] = 1
    with pytest.raises(profile.ProfileError, match="template venue, format: unknown keys 7"):
        _load(tmp_path, data)


def test_profile_file_in_another_encoding_than_utf_8_is_rejected_as_a_template(tmp_path):
    path = tmp_path / "venue.yaml"
    path.write_bytes("name: Caf\u00e9\n".encode("latin-1"))
    with pytest.raises(profile.ProfileError, match="template venue: the file is not saved as UTF-8"):
        profile.load(str(path))


def test_file_pattern_needs_one_group(tmp_path):
    data = _shipped("icse-2027")
    data["file_pattern"] = r"paper\d+\.pdf"
    with pytest.raises(profile.ProfileError, match="one group"):
        _load(tmp_path, data)


def test_options_of_an_unset_check_are_empty():
    assert profile.load("icse-2027").options("no-such-check") == {}


def test_shipped_profiles_set_lower_limits_for_the_body_font_and_the_line_spacing():
    for key in profile.available():
        rules = profile.load(key).format
        assert rules.body_font_min < 10.3 and rules.leading_min < 12


def test_lower_limits_for_the_body_font_and_the_line_spacing_are_optional(tmp_path):
    data = _shipped("icse-2027")
    del data["format"]["body_font_min"], data["format"]["leading_min"]
    rules = _load(tmp_path, data).format
    assert (rules.body_font_min, rules.leading_min) == (None, None)


def test_a_check_runs_while_its_key_stands_in_the_template(tmp_path):
    data = _shipped("icse-2027")
    del data["checks"]["references"]
    venue = _load(tmp_path, data)
    assert venue.runs("hidden_text") and venue.options("hidden_text") == {}
    assert not venue.runs("references")


def test_every_check_of_the_default_template_runs_except_the_accessibility_notes():
    venue = profile.load(profile.DEFAULT)
    keys = ("layout", "sigsoft", "hidden_text", "references", "cocodet", "editlens", "duplicates", "citations",
            "short_reviews", "canary", "conflicts")
    assert all(venue.runs(key) for key in keys) and not venue.runs("accessibility")


@pytest.mark.parametrize("settings", [False, True, {"enabled": False}], ids=["false", "true", "enabled"])
def test_a_switch_in_place_of_a_commented_out_key_is_refused_with_the_way_to_turn_a_check_off(tmp_path, settings):
    data = _shipped("icse-2027")
    data["checks"]["references"] = settings
    with pytest.raises(profile.ProfileError, match="a # before the key references turns the check off"):
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
    data["checks"]["hidden_text"] = {"extra_phrases": [{"phrase": "accept"}]}
    with pytest.raises(profile.ProfileError, match="extra_phrases"):
        _load(tmp_path, data)

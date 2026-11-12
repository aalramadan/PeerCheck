"""Tests of the command line of PeerCheck, whose commands are options such as --papers."""
import importlib.util
import shutil

import pytest

from peercheck import cli, tools
from peercheck.papers import pipeline


def _papers_run(*args):
    """Stand in for the paper checks with a run that found no PDF."""
    return pipeline.PapersRun([], {}, {}, [], ("layout",))


def _used_venue(monkeypatch):
    used = []
    monkeypatch.setattr(cli.pipeline, "run_papers", lambda *args: used.append(args) or _papers_run())
    return used


def test_papers_command_without_a_profile_applies_the_default_rules(monkeypatch, tmp_path, capsys):
    used = _used_venue(monkeypatch)
    assert cli.main(["--papers", str(tmp_path), "--out", str(tmp_path / "r.xlsx")]) == 0
    assert used[0][1].name == "Default rules"
    assert "profiles/default.yaml" in capsys.readouterr().err


def test_profile_may_come_before_or_after_the_command(monkeypatch, tmp_path):
    used = _used_venue(monkeypatch)
    assert cli.main(["--papers", str(tmp_path), "--profile", "icse-2027", "--out", str(tmp_path / "r.xlsx")]) == 0
    assert cli.main(["--profile", "fse-2027", "--papers", str(tmp_path), "--out", str(tmp_path / "r.xlsx")]) == 0
    assert [args[1].name for args in used] == ["ICSE 2027 Research Track", "FSE 2027 Research Track"]


def test_papers_command_leaves_the_choice_of_checks_to_the_venue_rules(monkeypatch, tmp_path):
    used = _used_venue(monkeypatch)
    assert cli.main(["--profile", "icse-2027", "--papers", str(tmp_path), "--out", str(tmp_path / "r.xlsx")]) == 0
    assert len(used[0]) == 4


def test_only_one_command_runs_at_a_time():
    with pytest.raises(SystemExit):
        cli.parser().parse_args(["--papers", "submissions", "--reviews", "reviews"])


def test_an_option_of_another_command_is_refused(tmp_path, capsys):
    assert cli.main(["--papers", str(tmp_path), "--pc", "pc.csv"]) == 2
    assert "--pc does not work with --papers" in capsys.readouterr().err


@pytest.mark.parametrize("argv", [["--papers", "pdfs", "--checks", "layout"], ["--papers", "pdfs", "--html", "r.html"],
                                  ["--conflicts", "--authors", "a.csv", "--pc", "pc.csv", "--years", "2"]])
def test_settings_are_no_options_of_the_command_line(argv):
    with pytest.raises(SystemExit):
        cli.parser().parse_args(argv)


def test_command_line_refuses_an_abbreviated_option():
    with pytest.raises(SystemExit):
        cli.parser().parse_args(["--prof", "fse-2027", "--papers", "submissions"])


def test_papers_command_writes_the_html_page_beside_the_workbook_by_default(monkeypatch, tmp_path):
    monkeypatch.setattr(cli.pipeline, "run_papers", _papers_run)
    assert cli.main(["--profile", "icse-2027", "--papers", str(tmp_path), "--out", str(tmp_path / "venue.xlsx")]) == 0
    assert (tmp_path / "venue.xlsx").is_file() and (tmp_path / "venue.html").is_file()


def test_papers_command_writes_the_json_and_html_reports_when_the_workbook_fails(monkeypatch, tmp_path):
    def locked(*args):
        raise PermissionError("report.xlsx is open in another program")

    monkeypatch.setattr(cli.pipeline, "run_papers", _papers_run)
    monkeypatch.setattr(cli.report, "write_papers", locked)
    argv = ["--profile", "icse-2027", "--papers", str(tmp_path), "--out", str(tmp_path / "report.xlsx"),
            "--json", str(tmp_path / "report.json")]
    assert cli.main(argv) == 2
    assert (tmp_path / "report.json").is_file() and (tmp_path / "report.html").is_file()


def _review_command(monkeypatch, argv):
    """Run the reviews command and return the command line that it hands to the review checks."""
    calls = []
    monkeypatch.setattr(cli.importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(cli.subprocess, "call", lambda command: calls.append(command) or 0)
    assert cli.main(argv) == 0
    return calls[0][3:]


def test_reviews_command_hands_its_options_and_its_folder_to_the_review_checks(monkeypatch):
    argv = ["--profile", "fse-2027", "--reviews", "exports", "--canaries", "key.csv"]
    assert _review_command(monkeypatch, argv) == ["--profile", "fse-2027", "--canaries", "key.csv", "--", "exports"]


def test_reviews_folder_whose_name_starts_with_a_dash_stays_a_folder(monkeypatch):
    argv = ["--reviews=-exports", "--out", "reviews.xlsx"]
    assert _review_command(monkeypatch, argv) == ["--out", "reviews.xlsx", "--", "-exports"]


def test_canary_command_needs_the_output_folder_and_the_key_file(tmp_path, capsys):
    assert cli.main(["--canary", str(tmp_path)]) == 2
    assert "--canary needs" in capsys.readouterr().err


def _served(monkeypatch):
    served = []
    monkeypatch.setattr(cli.gui, "serve", lambda *args: served.append(args) or 0)
    return served


def test_gui_with_an_unknown_profile_stops_before_the_page_starts(monkeypatch, capsys):
    served = _served(monkeypatch)
    assert cli.main(["--profile", "no-such-venue", "--gui", "--no-browser"]) == 2
    assert not served and "unknown profile 'no-such-venue'" in capsys.readouterr().err


@pytest.mark.parametrize("value", ["abc", "70000"])
def test_wrong_gui_port_in_the_environment_stops_only_the_gui_command(monkeypatch, value):
    monkeypatch.setenv("PEERCHECK_GUI_PORT", value)
    served = _served(monkeypatch)
    assert cli.parser().parse_args(["--setup"]).setup
    assert cli.main(["--gui", "--no-browser"]) == 2
    assert not served


def test_empty_gui_port_in_the_environment_picks_a_free_port(monkeypatch):
    monkeypatch.setenv("PEERCHECK_GUI_PORT", "")
    served = _served(monkeypatch)
    assert cli.main(["--gui", "--no-browser"]) == 0
    assert served[0][1] == 0


@pytest.mark.parametrize("port", ["70000", "-1"])
def test_gui_port_outside_0_to_65535_is_a_usage_error(port):
    with pytest.raises(SystemExit) as stop:
        cli.parser().parse_args(["--gui", "--port", port])
    assert stop.value.code == 2


def test_gui_listens_only_on_the_addresses_whose_page_a_browser_can_open(monkeypatch):
    assert [cli.parser().parse_args(["--gui", "--host", host]).host
            for host in ("127.0.0.1", "localhost", "0.0.0.0")] == ["127.0.0.1", "localhost", "0.0.0.0"]
    with pytest.raises(SystemExit):
        cli.parser().parse_args(["--gui", "--host", "192.168.1.5"])
    monkeypatch.setenv("PEERCHECK_GUI_HOST", "192.168.1.5")
    served = _served(monkeypatch)
    assert cli.main(["--gui", "--no-browser"]) == 2
    assert not served


def test_installed_package_finds_the_external_files_that_its_wheel_holds(tmp_path):
    package = tmp_path / "site-packages" / "peercheck"
    for relative in ("hotcrp/banal", "submission-checker/submission-checker.jar", "census-surnames/census_surnames.txt"):
        (package / "external" / relative).parent.mkdir(parents=True, exist_ok=True)
        (package / "external" / relative).touch()
    shutil.copy(tools.__file__, package / "tools.py")
    spec = importlib.util.spec_from_file_location("installed_tools", package / "tools.py")
    installed = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installed)
    assert installed.banal() == package.resolve() / "external" / "hotcrp" / "banal"
    assert all(path.is_file() for path in (installed.banal(), installed.submission_checker(), installed.census_surnames()))


def test_no_command_prints_the_help(capsys):
    assert cli.main([]) == 0
    assert capsys.readouterr().out.startswith("usage: peercheck")


def test_setup_downloads_the_reference_database(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(cli.references, "install_tools", lambda *args: calls.append(args) or [tmp_path / "dblp.db"])
    assert cli.main(["--setup", "--refresh"]) == 0
    assert calls == [(cli.tools.cache_dir(), None, None, True)]

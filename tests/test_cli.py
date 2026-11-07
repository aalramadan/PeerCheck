"""Tests of the command line of PeerCheck."""
import importlib.util
import shutil

import pytest

from peercheck import cli, pipeline, tools


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


def test_reviews_command_hands_a_double_dash_and_the_folder_after_it_to_the_review_checks(monkeypatch):
    argv = ["reviews", "--out", "reviews.xlsx", "--", "-exports"]
    assert _review_command(monkeypatch, argv) == ["--profile", "icse-2027", "--out", "reviews.xlsx", "--", "-exports"]


def test_command_line_refuses_an_abbreviated_profile_option():
    with pytest.raises(SystemExit):
        cli.parser().parse_args(["--prof", "fse-2027", "papers", "submissions"])


def _papers_run(*args):
    """Stand in for the paper checks with a run that found no PDF."""
    return pipeline.PapersRun([], {}, [], [], ("layout",))


def test_papers_command_runs_a_repeated_check_once(monkeypatch, tmp_path):
    requested = []
    monkeypatch.setattr(cli.pipeline, "run_papers", lambda *args: requested.append(args[4]) or _papers_run())
    argv = ["papers", str(tmp_path), "--checks", "hidden-text, hidden-text,layout", "--out", str(tmp_path / "r.xlsx")]
    assert cli.main(argv) == 0
    assert requested == [["hidden-text", "layout"]]


def test_papers_command_writes_the_json_and_html_reports_when_the_workbook_fails(monkeypatch, tmp_path):
    def locked(*args):
        raise PermissionError("report.xlsx is open in another program")

    monkeypatch.setattr(cli.pipeline, "run_papers", _papers_run)
    monkeypatch.setattr(cli.report, "write_papers", locked)
    argv = ["papers", str(tmp_path), "--out", str(tmp_path / "report.xlsx"), "--json", str(tmp_path / "report.json"),
            "--html", str(tmp_path / "report.html")]
    assert cli.main(argv) == 2
    assert (tmp_path / "report.json").is_file() and (tmp_path / "report.html").is_file()


def test_gui_with_an_unknown_profile_stops_before_the_page_starts(monkeypatch, capsys):
    served = []
    monkeypatch.setattr(cli.gui, "serve", lambda *args: served.append(args) or 0)
    assert cli.main(["--profile", "no-such-venue", "gui", "--no-browser"]) == 2
    assert not served and "unknown profile 'no-such-venue'" in capsys.readouterr().err


@pytest.mark.parametrize("value", ["abc", "70000"])
def test_wrong_gui_port_in_the_environment_stops_only_the_gui_command(monkeypatch, value):
    monkeypatch.setenv("PEERCHECK_GUI_PORT", value)
    assert cli.parser().parse_args(["doctor"]).command == "doctor"
    with pytest.raises(SystemExit):
        cli.parser().parse_args(["gui"])


def test_empty_gui_port_in_the_environment_picks_a_free_port(monkeypatch):
    monkeypatch.setenv("PEERCHECK_GUI_PORT", "")
    assert cli.parser().parse_args(["gui"]).port == 0


@pytest.mark.parametrize("port", ["70000", "-1"])
def test_gui_port_outside_0_to_65535_is_a_usage_error(port):
    with pytest.raises(SystemExit) as stop:
        cli.parser().parse_args(["gui", "--port", port])
    assert stop.value.code == 2


def test_gui_listens_only_on_the_addresses_whose_page_a_browser_can_open(monkeypatch):
    assert [cli.parser().parse_args(["gui", "--host", host]).host
            for host in ("127.0.0.1", "localhost", "0.0.0.0")] == ["127.0.0.1", "localhost", "0.0.0.0"]
    with pytest.raises(SystemExit):
        cli.parser().parse_args(["gui", "--host", "192.168.1.5"])
    monkeypatch.setenv("PEERCHECK_GUI_HOST", "192.168.1.5")
    with pytest.raises(SystemExit):
        cli.parser().parse_args(["gui"])


def test_doctor_reports_a_missing_census_list(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(tools, "EXTERNAL", tmp_path)
    assert cli.main(["doctor"]) == 1
    assert "missing census_surnames.txt" in capsys.readouterr().out


def test_doctor_reports_missing_data_of_the_conflict_check(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(tools, "EXTERNAL", tmp_path)
    cli.main(["doctor"])
    printed = capsys.readouterr().out
    assert "missing affiliationmatchers.json" in printed and "missing public_suffix_list.dat" in printed


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
    assert not {"banal", "submission-checker.jar", "census_surnames.txt"} & set(installed.missing())


def _menu_commands(monkeypatch, answers):
    """Answer the prompts of the menu in order and return the command lines that the menu runs."""
    replies = iter(answers)
    commands = []
    monkeypatch.setattr("builtins.input", lambda prompt="": next(replies))
    monkeypatch.setattr(cli, "main", lambda argv: commands.append(argv) or 0)
    assert cli.menu("icse-2027") == 0
    return commands


@pytest.mark.parametrize(("answer", "detectors"), [("cocodet", "cocodet"), ("none", ""), ("", "cocodet,editlens")])
def test_menu_asks_which_ai_detectors_the_review_checks_run(monkeypatch, answer, detectors):
    commands = _menu_commands(monkeypatch, ["2", "exports", answer, "reviews.xlsx", "4"])
    assert commands == [["--profile", "icse-2027", "reviews", "exports", "--detectors", detectors,
                         "--out", "reviews.xlsx"]]


def test_menu_warns_about_a_submission_sheet_that_does_not_exist(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    commands = _menu_commands(monkeypatch, ["1", "submissions", "submisions.xlsx", "none", "report.xlsx", "4"])
    assert commands == [["--profile", "icse-2027", "papers", "submissions", "--out", "report.xlsx"]]
    assert "submisions.xlsx not found" in capsys.readouterr().out


def test_menu_goes_on_after_an_answer_that_the_command_line_refuses(monkeypatch, capsys):
    replies = iter(["1", "--bogus", "none", "none", "report.xlsx", "4"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(replies))
    assert cli.menu("icse-2027") == 0
    assert "Finished with exit code 2." in capsys.readouterr().out

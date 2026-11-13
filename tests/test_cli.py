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
    assert cli.main(["--papers", str(tmp_path), "--out", str(tmp_path / "r.csv")]) == 0
    assert used[0][1].name == "Default template"
    assert "templates/default.yaml" in capsys.readouterr().err


def test_profile_may_come_before_or_after_the_command(monkeypatch, tmp_path):
    used = _used_venue(monkeypatch)
    assert cli.main(["--papers", str(tmp_path), "--template", "icse-2027", "--out", str(tmp_path / "r.csv")]) == 0
    assert cli.main(["--template", "fse-2027", "--papers", str(tmp_path), "--out", str(tmp_path / "r.csv")]) == 0
    assert [args[1].name for args in used] == ["ICSE 2027 Research Track", "FSE 2027 Research Track"]


def test_papers_command_leaves_the_choice_of_checks_to_the_venue_rules(monkeypatch, tmp_path):
    used = _used_venue(monkeypatch)
    assert cli.main(["--template", "icse-2027", "--papers", str(tmp_path), "--out", str(tmp_path / "r.csv")]) == 0
    assert len(used[0]) == 4


def test_papers_command_names_the_checks_that_the_template_turns_off(monkeypatch, tmp_path, capsys):
    _used_venue(monkeypatch)
    template = tmp_path / "template.yaml"
    template.write_text((cli.profiles.PROFILES / "icse-2027.yaml").read_text(encoding="utf-8")
                        .replace("  references:\n", "  # references:\n"), encoding="utf-8")
    assert cli.main(["--template", str(template), "--papers", str(tmp_path), "--out", str(tmp_path / "r.csv")]) == 0
    assert "The template turns off references." in capsys.readouterr().err


def test_conflicts_command_stops_while_the_template_leaves_out_the_key_conflicts(tmp_path, capsys):
    template = tmp_path / "template.yaml"
    template.write_text((cli.profiles.PROFILES / "icse-2027.yaml").read_text(encoding="utf-8")
                        .replace("  conflicts:\n", ""), encoding="utf-8")
    assert cli.main(["--template", str(template), "--conflicts", "--authors", "a.csv", "--pc", "pc.csv"]) == 2
    assert "remove the # before the key conflicts" in capsys.readouterr().err


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


def test_papers_command_writes_the_html_page_beside_the_csv_file(monkeypatch, tmp_path):
    monkeypatch.setattr(cli.pipeline, "run_papers", _papers_run)
    assert cli.main(["--template", "icse-2027", "--papers", str(tmp_path), "--out", str(tmp_path / "venue.csv")]) == 0
    assert (tmp_path / "venue.csv").is_file() and (tmp_path / "venue.html").is_file()


def test_papers_command_writes_the_html_report_when_the_csv_file_fails(monkeypatch, tmp_path, capsys):
    def locked(*args):
        raise PermissionError("report.csv is open in another program")

    monkeypatch.setattr(cli.pipeline, "run_papers", _papers_run)
    monkeypatch.setattr(cli.report, "write_csv", locked)
    argv = ["--template", "icse-2027", "--papers", str(tmp_path), "--out", str(tmp_path / "report.csv")]
    assert cli.main(argv) == 2
    assert (tmp_path / "report.html").is_file() and "report.csv is open" in capsys.readouterr().err


def test_papers_command_names_the_pdfs_that_it_numbered_or_skipped(monkeypatch, tmp_path, capsys):
    run = pipeline.PapersRun([], {}, {13: "notes.pdf"}, ["CONF_2026_paper_7 (1).pdf"], ("layout",))
    monkeypatch.setattr(cli.pipeline, "run_papers", lambda *args: run)
    assert cli.main(["--papers", str(tmp_path), "--out", str(tmp_path / "r.csv")]) == 0
    err = capsys.readouterr().err
    assert "notes.pdf holds no paper number; checked as paper 13" in err
    assert "skipped CONF_2026_paper_7 (1).pdf, which repeats a paper number" in err


def test_papers_command_writes_its_report_under_a_name_that_no_input_takes(monkeypatch, tmp_path):
    monkeypatch.setattr(cli.pipeline, "run_papers", _papers_run)
    monkeypatch.chdir(tmp_path)
    assert cli.main(["--papers", str(tmp_path)]) == 0
    assert (tmp_path / "papers-report.csv").is_file() and (tmp_path / "papers-report.html").is_file()


@pytest.mark.parametrize("out", ["report.xlsx", "authors.csv"])
def test_report_that_is_an_excel_file_or_an_input_is_refused(monkeypatch, tmp_path, out, capsys):
    monkeypatch.setattr(cli.pipeline, "run_papers", _papers_run)
    (tmp_path / "authors.csv").write_text("paper,first,last\n1,Ana,Ruiz\n")
    argv = ["--papers", str(tmp_path), "--authors", str(tmp_path / "authors.csv"), "--out", str(tmp_path / out)]
    assert cli.main(argv) == 2
    assert "--out" in capsys.readouterr().err and (tmp_path / "authors.csv").read_text().startswith("paper,first")


def test_json_output_is_no_option_of_the_command_line():
    with pytest.raises(SystemExit):
        cli.parser().parse_args(["--papers", "pdfs", "--json", "report.json"])


def _review_command(monkeypatch, argv):
    """Run the reviews command and return the command line that it hands to the review checks."""
    calls = []
    monkeypatch.setattr(cli.importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(cli.subprocess, "call", lambda command: calls.append(command) or 0)
    assert cli.main(argv) == 0
    return calls[0][3:]


def test_reviews_command_hands_its_options_and_its_file_to_the_review_checks(monkeypatch):
    argv = ["--template", "fse-2027", "--reviews", "reviews.csv", "--canaries", "key.csv"]
    assert _review_command(monkeypatch, argv) == ["--template", "fse-2027", "--canaries", "key.csv", "--", "reviews.csv"]


def test_reviews_file_whose_name_starts_with_a_dash_stays_a_file(monkeypatch):
    argv = ["--reviews=-reviews.csv", "--out", "report.csv"]
    assert _review_command(monkeypatch, argv) == ["--out", "report.csv", "--", "-reviews.csv"]


def test_canary_command_needs_the_output_folder_and_the_key_file(tmp_path, capsys):
    assert cli.main(["--canary", str(tmp_path)]) == 2
    assert "--canary needs" in capsys.readouterr().err


def _served(monkeypatch):
    served = []
    monkeypatch.setattr(cli.gui, "serve", lambda *args: served.append(args) or 0)
    return served


def test_gui_with_an_unknown_profile_stops_before_the_page_starts(monkeypatch, capsys):
    served = _served(monkeypatch)
    assert cli.main(["--template", "no-such-venue", "--gui"]) == 2
    assert not served and "unknown template 'no-such-venue'" in capsys.readouterr().err


@pytest.mark.parametrize("value", ["abc", "70000"])
def test_wrong_gui_port_in_the_environment_stops_only_the_gui_command(monkeypatch, value):
    monkeypatch.setenv("PEERCHECK_GUI_PORT", value)
    served = _served(monkeypatch)
    assert cli.parser().parse_args(["--setup"]).setup
    assert cli.main(["--gui"]) == 2
    assert not served


def test_empty_gui_port_in_the_environment_picks_a_free_port(monkeypatch):
    monkeypatch.setenv("PEERCHECK_GUI_PORT", "")
    served = _served(monkeypatch)
    assert cli.main(["--gui"]) == 0
    assert served[0][1] == 0


@pytest.mark.parametrize("option", [["--host", "0.0.0.0"], ["--port", "8765"], ["--no-browser"]])
def test_gui_takes_no_address_port_or_browser_option(option):
    with pytest.raises(SystemExit):
        cli.parser().parse_args(["--gui", *option])


def test_gui_opens_the_browser_at_a_local_address_and_a_free_port(monkeypatch):
    monkeypatch.delenv("PEERCHECK_GUI_HOST", raising=False)
    monkeypatch.delenv("PEERCHECK_GUI_PORT", raising=False)
    served = _served(monkeypatch)
    assert cli.main(["--gui"]) == 0
    assert served == [(None, 0, True, "127.0.0.1")]


def test_gui_refuses_an_address_in_the_environment_whose_page_a_browser_cannot_open(monkeypatch, capsys):
    monkeypatch.setenv("PEERCHECK_GUI_HOST", "192.168.1.5")
    served = _served(monkeypatch)
    assert cli.main(["--gui"]) == 2
    assert not served and "PEERCHECK_GUI_HOST" in capsys.readouterr().err


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


def test_interrupt_ends_a_command_with_one_line_and_the_exit_status_of_the_signal(monkeypatch, capsys):
    def interrupted(args):
        raise KeyboardInterrupt

    monkeypatch.setitem(cli.RUNNERS, "setup", interrupted)
    assert cli.main(["--setup"]) == 130
    assert capsys.readouterr().err == "peercheck: stopped\n"


def test_no_command_prints_the_help(capsys):
    assert cli.main([]) == 0
    assert capsys.readouterr().out.startswith("usage: peercheck")


def test_help_lists_the_commands_before_one_group_of_options():
    text = cli.parser().format_help()
    assert text.count("options:") == 1 and text.index("commands, one per run:") < text.index("options:")
    assert all(option in text.split("options:")[1] for option in ("--template", "--help", "--version"))


def test_setup_downloads_the_reference_database(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(cli.reference_setup, "install_tools",
                        lambda *args: calls.append(args) or [tmp_path / "dblp.db"])
    assert cli.main(["--setup", "--refresh"]) == 0
    assert calls == [(cli.tools.cache_dir(), None, True)]

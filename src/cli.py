"""Command line of PeerCheck, whose commands are options, such as --papers and --reviews."""

from __future__ import annotations

import argparse
import importlib.util
import os
import signal
import subprocess
import sys
from pathlib import Path

from peercheck import __version__, canary, conflicts, dblp, gui, inputs, report, tools
from peercheck import profile as profiles
from peercheck.findings import needs_review
from peercheck.models import Person
from peercheck.papers import pipeline, reference_setup

COMMANDS = ("papers", "reviews", "conflicts", "canary", "setup", "gui")
# The options that each command reads. Any other option beside a command is a mistake that stops the run.
OPTIONS = {
    "papers": {"template", "out", "submissions", "authors"},
    "reviews": {"template", "out", "canaries"},
    "conflicts": {"template", "out", "authors", "pc"},
    "canary": {"template", "out", "canaries"},
    "setup": {"retraction_csv", "refresh"},
    "gui": {"template"},
}
EXPECTED_ERRORS = (inputs.InputError, profiles.ProfileError, tools.ToolError, ValueError, OSError)


def main(argv: list[str] | None = None) -> int:
    """Run the command given on the command line, or print the help when none is given."""
    top = parser()
    args = top.parse_args(sys.argv[1:] if argv is None else list(argv))
    command = next((name for name in COMMANDS if getattr(args, name) not in (None, False)), None)
    if command is None:
        top.print_help()
        return 0
    try:
        _check_options(args, command)
        return RUNNERS[command](args)
    except EXPECTED_ERRORS as exc:
        print(f"peercheck: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("peercheck: stopped", file=sys.stderr)
        # The exit status that a shell gives a command that Ctrl+C ends.
        return 128 + signal.SIGINT


def parser() -> argparse.ArgumentParser:
    """Build the parser of the command line, with one command per run."""
    top = argparse.ArgumentParser(prog="peercheck", allow_abbrev=False, add_help=False,
                                  description="Check the submissions, the reviews, and the conflicts of interest of "
                                              "IEEE and ACM venues.")
    commands = top.add_argument_group("commands, one per run").add_mutually_exclusive_group()
    commands.add_argument("--papers", type=Path, metavar="FOLDER", help="check the submission PDFs of a folder")
    commands.add_argument("--reviews", type=Path, metavar="FILE", help="check the reviews of a CSV file")
    commands.add_argument("--conflicts", action="store_true",
                          help="find conflicts of interest between the authors and the committee")
    commands.add_argument("--canary", type=Path, metavar="FOLDER",
                          help="insert a fictitious citation into each PDF of a folder")
    commands.add_argument("--setup", action="store_true", help="download Hallucinator, DBLP, and the Retraction Watch data")
    commands.add_argument("--gui", action="store_true", help="open the browser interface")

    options = top.add_argument_group("options")
    options.add_argument("--template", metavar="FILE", help="the template of the venue, a copy of "
                         "templates/default.yaml or an example such as icse-2027 (default templates/default.yaml)")
    options.add_argument("--out", type=Path, metavar="PATH", help="the CSV report, with the HTML report beside it "
                         "(default papers-report.csv, reviews-report.csv, or conflicts-report.csv), or the folder of "
                         "the PDFs of --canary")
    options.add_argument("--submissions", type=Path, metavar="FILE",
                         help="submissions file (CSV) with the columns paper and title, for --papers")
    options.add_argument("--authors", type=Path, metavar="FILE", help="authors file (CSV) with the columns paper, "
                         "first, last, email, and affiliation, for --papers and --conflicts")
    options.add_argument("--pc", type=Path, metavar="FILE", help="committee file (CSV) with the columns first, last, "
                         "email, affiliation, and dblp, for --conflicts")
    options.add_argument("--canaries", type=Path, metavar="FILE",
                         help="canary key file, which --canary writes and --reviews reads")
    options.add_argument("--retraction-csv", type=Path, metavar="FILE",
                         help="local Retraction Watch file (CSV) for --setup, in place of its download")
    options.add_argument("--refresh", action="store_true", help="download every file of --setup again")
    # Beside the other options, since argparse lists its own --help under a second heading "options".
    options.add_argument("-h", "--help", action="help", help="show this help and exit")
    options.add_argument("--version", action="version", version=f"PeerCheck {__version__}",
                         help="show the version and exit")
    return top


def _check_options(args: argparse.Namespace, command: str) -> None:
    """Refuse an option that the command does not read, such as --pc beside --papers."""
    wrong = [name for name, value in vars(args).items()
             if name not in COMMANDS and value not in (None, False) and name not in OPTIONS[command]]
    if wrong:
        flags = ", ".join("--" + name.replace("_", "-") for name in wrong)
        raise inputs.InputError(f"{flags} does not work with --{command}")


def _gui_address() -> tuple[str, int]:
    """Return the address and the port of the page: 127.0.0.1 and a free port, unless the environment sets them.

    The Docker image sets PEERCHECK_GUI_HOST and PEERCHECK_GUI_PORT, since a container must listen on every address of
    a known port."""
    host = os.environ.get("PEERCHECK_GUI_HOST") or "127.0.0.1"
    if host not in gui.LISTEN_ADDRESSES:
        raise inputs.InputError(f"PEERCHECK_GUI_HOST holds {host!r}; choose {', '.join(gui.LISTEN_ADDRESSES)}")
    port = os.environ.get("PEERCHECK_GUI_PORT") or "0"
    if not port.isdecimal() or int(port) > 65535:
        raise inputs.InputError(f"PEERCHECK_GUI_PORT holds {port!r}; choose 0 to 65535, where 0 picks a free port")
    return host, int(port)


def _option(flag: str, value: Path | str | None) -> list[str]:
    return [flag, str(value)] if value else []


def run_papers(args: argparse.Namespace) -> int:
    """Check a folder of submission PDFs and write the report."""
    venue = profiles.load(args.template or profiles.DEFAULT)
    if not args.template:
        rules = venue.format
        print(f"The default template templates/default.yaml applies: {rules.style}, {rules.columns} columns, "
              f"{rules.main_pages} pages plus {rules.reference_pages} for references. Copy the file to set the rules "
              "of the venue and pass the copy with --template.", file=sys.stderr)
    off = [key for key in pipeline.PROFILE_KEYS.values() if not venue.runs(key)]
    if off:
        print(f"The template turns off {', '.join(off)}.", file=sys.stderr)
    out = report.csv_path(args.out, "papers-report.csv", args.submissions, args.authors)
    run = pipeline.run_papers(args.papers, venue, args.submissions, args.authors)
    # The page comes first, since the CSV file can fail, such as when it is open in Excel.
    page = out.with_suffix(".html")
    report.write_papers_html(page, run)
    report.write_csv(out, report.paper_rows(run))
    flagged = sum(1 for result in run.results if needs_review(result.findings))
    print(f"{len(run.results)} papers checked, {flagged} need review. Report: {page} and {out}")
    for paper_id, name in sorted(run.numbered.items()):
        print(f"{name} holds no paper number; checked as paper {paper_id}", file=sys.stderr)
    for name in run.duplicates:
        print(f"skipped {name}, which repeats a paper number", file=sys.stderr)
    return 0


def run_reviews(args: argparse.Namespace) -> int:
    """Run the review checks in their own process, since they load PyTorch and the detector models."""
    if importlib.util.find_spec("torch") is None:
        raise tools.ToolError("the review checks need PyTorch, which pip install . installs with PeerCheck")
    options = [*_option("--template", args.template), *_option("--canaries", args.canaries),
               *_option("--out", args.out)]
    # The double dash keeps a file whose name starts with a dash from reading as an option.
    return subprocess.call([sys.executable, "-m", "peercheck.reviews", *options, "--", str(args.reviews)])


def run_conflicts(args: argparse.Namespace) -> int:
    """Find conflicts of interest from the authors and committee files and write the report."""
    if not args.authors or not args.pc:
        raise inputs.InputError("--conflicts needs the authors file of --authors and the committee file of --pc")
    venue = profiles.load(args.template or profiles.DEFAULT)
    if not venue.runs("conflicts"):
        raise inputs.InputError("the template turns the conflict check off; remove the # before the key conflicts")
    out = report.csv_path(args.out, "conflicts-report.csv", args.authors, args.pc)
    authors = inputs.read_people(args.authors, with_paper=True)
    committee = inputs.read_people(args.pc, with_paper=False)
    people = list(dict.fromkeys([person for group in authors.values() for person in group] + committee))
    index = _coauthor_index(people)
    found = conflicts.find_conflicts(authors, committee, index, venue.options("conflicts"))
    rows = conflicts.rows(found)
    page = out.with_suffix(".html")
    report.write_conflicts_html(page, rows, [f"DBLP: {'used' if index is not None else 'not used'}."])
    report.write_csv(out, rows)
    print(f"{len(found)} possible conflicts. Report: {page} and {out}")
    return 0


def _coauthor_index(people: list[Person]) -> dblp.DblpIndex | None:
    """Return the co-author index of the people from the DBLP copy of --setup, or None before --setup."""
    dump, _dtd, saved = dblp.files(tools.cache_dir())
    if not dump.is_file():
        print("Co-authorship stays out of the check, since peercheck --setup has not downloaded DBLP.", file=sys.stderr)
        return None
    # An index saved from the same dump that holds every listed person spares the scan of the dump.
    if saved.is_file() and saved.stat().st_mtime >= dump.stat().st_mtime:
        try:
            index = dblp.load_index(saved)
        except (OSError, ValueError, KeyError):
            index = None
        if index is not None and not index.missing(people):
            return index
    print("Reading the co-authors of the listed people from DBLP.", file=sys.stderr)
    index = dblp.build_index(dump, people)
    index.save(saved)
    return index


def run_canary(args: argparse.Namespace) -> int:
    """Write a copy of each submission PDF with its hidden citation and update the key file."""
    if not args.out or not args.canaries:
        raise inputs.InputError("--canary needs the folder of the marked PDFs in --out and the key file in --canaries")
    venue = profiles.load(args.template or profiles.DEFAULT)
    count, skipped = canary.mark_folder(args.canary, args.out, args.canaries, venue)
    print(f"{count} PDFs marked in {args.out}. Key: {args.canaries}")
    for name in skipped:
        print(f"skipped {name}", file=sys.stderr)
    return 0


def run_setup(args: argparse.Namespace) -> int:
    """Download Hallucinator, the DBLP database, and the Retraction Watch list of the reference check."""
    for path in reference_setup.install_tools(tools.cache_dir(), args.retraction_csv, args.refresh):
        print(f"installed {path}")
    return 0


def run_gui(args: argparse.Namespace) -> int:
    """Serve the checks as a page in the browser until Ctrl+C."""
    host, port = _gui_address()
    # The page offers the template of the session first, therefore a template that does not load stops here.
    if args.template:
        profiles.load(args.template)
    # A container listens on every address and holds no browser, therefore only a local address opens one.
    return gui.serve(args.template, port, host in gui.LOCAL_NAMES, host)


RUNNERS = {"papers": run_papers, "reviews": run_reviews, "conflicts": run_conflicts, "canary": run_canary,
           "setup": run_setup, "gui": run_gui}

"""Command line of PeerCheck, whose commands are options, such as --papers and --reviews."""

from __future__ import annotations

import argparse
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

from peercheck import __version__, canary, conflicts, dblp, gui, inputs, report, tools
from peercheck import profile as profiles
from peercheck.findings import needs_review
from peercheck.papers import pipeline, references

COMMANDS = ("papers", "reviews", "conflicts", "canary", "setup", "gui")
# The options that each command reads. Any other option beside a command is a mistake that stops the run.
OPTIONS = {
    "papers": {"profile", "out", "json", "submissions", "authors"},
    "reviews": {"profile", "out", "json", "canaries", "dblp_index"},
    "conflicts": {"profile", "out", "authors", "pc", "dblp_dump", "dblp_index", "save_index"},
    "canary": {"profile", "out", "canaries"},
    "setup": {"dblp_dump", "retraction_csv", "refresh"},
    "gui": {"profile", "host", "port", "no_browser"},
}
EXPECTED_ERRORS = (inputs.InputError, profiles.ProfileError, tools.ToolError, ValueError, OSError,
                   argparse.ArgumentTypeError)


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


def parser() -> argparse.ArgumentParser:
    """Build the parser of the command line, with one command per run."""
    top = argparse.ArgumentParser(prog="peercheck", allow_abbrev=False,
                                  description="Check the submissions, the reviews, and the conflicts of interest of a "
                                              "conference or a journal.")
    commands = top.add_argument_group("commands, one per run").add_mutually_exclusive_group()
    commands.add_argument("--papers", type=Path, metavar="FOLDER", help="check the submission PDFs of a folder")
    commands.add_argument("--reviews", type=Path, metavar="PATH", help="check the reviews of a folder or a file")
    commands.add_argument("--conflicts", action="store_true",
                          help="find conflicts of interest between the authors and the committee")
    commands.add_argument("--canary", type=Path, metavar="FOLDER",
                          help="insert a fictitious citation into each PDF of a folder")
    commands.add_argument("--setup", action="store_true", help="download Hallucinator, DBLP, and the Retraction Watch list")
    commands.add_argument("--gui", action="store_true", help="open the browser interface")

    options = top.add_argument_group("options")
    options.add_argument("--profile", metavar="FILE", help="the rules and settings of the venue, a copy of "
                         "profiles/default.yaml or an example such as icse-2027 (default profiles/default.yaml)")
    options.add_argument("--out", type=Path, metavar="PATH", help="the Excel report, with the HTML report beside it "
                         "(default report.xlsx, reviews.xlsx, or conflicts.xlsx), or the folder of the PDFs of --canary")
    options.add_argument("--json", type=Path, metavar="FILE", help="JSON output of --papers or --reviews")
    options.add_argument("--submissions", type=Path, metavar="FILE",
                         help="submission sheet with the columns paper and title, for --papers")
    options.add_argument("--authors", type=Path, metavar="FILE", help="author list with the columns paper, first, "
                         "last, email, and affiliation, for --papers and --conflicts")
    options.add_argument("--pc", type=Path, metavar="FILE", help="committee list with the columns first, last, "
                         "email, affiliation, and dblp, for --conflicts")
    options.add_argument("--canaries", type=Path, metavar="FILE",
                         help="canary key file, which --canary writes and --reviews reads")
    options.add_argument("--dblp-dump", type=Path, metavar="FILE",
                         help="DBLP dump dblp.xml.gz, for --conflicts or --setup")
    options.add_argument("--dblp-index", type=Path, metavar="FILE",
                         help="co-author index that an earlier --conflicts saved, for --conflicts or --reviews")
    options.add_argument("--save-index", type=Path, metavar="FILE",
                         help="file for the co-author index that --conflicts builds from --dblp-dump")
    options.add_argument("--retraction-csv", type=Path, metavar="FILE",
                         help="local Retraction Watch list for --setup, in place of its download")
    options.add_argument("--refresh", action="store_true", help="download every file of --setup again")
    options.add_argument("--host", type=_gui_host, help=f"address of --gui: {', '.join(gui.LISTEN_ADDRESSES)} "
                                                       "(default 127.0.0.1)")
    options.add_argument("--port", type=_port, help="port of --gui (default a free port)")
    options.add_argument("--no-browser", action="store_true", help="start --gui without opening a browser")
    top.add_argument("--version", action="version", version=f"PeerCheck {__version__}")
    return top


def _check_options(args: argparse.Namespace, command: str) -> None:
    """Refuse an option that the command does not read, such as --pc beside --papers."""
    wrong = [name for name, value in vars(args).items()
             if name not in COMMANDS and value not in (None, False) and name not in OPTIONS[command]]
    if wrong:
        flags = ", ".join("--" + name.replace("_", "-") for name in wrong)
        raise inputs.InputError(f"{flags} does not work with --{command}")


def _gui_host(text: str) -> str:
    """Return an address that the page can listen on, or refuse it."""
    if text not in gui.LISTEN_ADDRESSES:
        raise argparse.ArgumentTypeError(f"invalid address {text!r}; choose {', '.join(gui.LISTEN_ADDRESSES)}")
    return text


def _port(text: str) -> int:
    """Return a port number from 0 to 65535, or refuse it."""
    if not text.isdecimal() or int(text) > 65535:
        raise argparse.ArgumentTypeError(f"invalid port {text!r}; choose 0 to 65535, where 0 picks a free port")
    return int(text)


def _option(flag: str, value: Path | str | None) -> list[str]:
    return [flag, str(value)] if value else []


def run_papers(args: argparse.Namespace) -> int:
    """Check a folder of submission PDFs and write the report."""
    venue = profiles.load(args.profile or profiles.DEFAULT)
    if not args.profile:
        rules = venue.format
        print(f"The default rules of profiles/default.yaml apply: {rules.style}, {rules.columns} columns, "
              f"{rules.main_pages} pages plus {rules.reference_pages} for references. Copy the file to set the rules "
              "of the venue and pass the copy with --profile.", file=sys.stderr)
    out = args.out or Path("report.xlsx")
    run = pipeline.run_papers(args.papers, venue, args.submissions, args.authors)
    # The JSON file and the page come first, since the workbook can fail, such as when it is open in Excel.
    page = out.with_suffix(".html")
    if args.json:
        report.write_json(args.json, run)
    report.write_papers_html(page, run)
    report.write_papers(out, run, venue, args.submissions)
    flagged = sum(1 for result in run.results if needs_review(result.findings))
    print(f"{len(run.results)} papers checked, {flagged} need review. Report: {page} and {out}")
    for paper_id, name in sorted(run.numbered.items()):
        print(f"{name} holds no paper number; checked as paper {paper_id}", file=sys.stderr)
    for name in run.duplicates:
        print(f"skipped {name}, which repeats a paper number; see the Files sheet", file=sys.stderr)
    return 0


def run_reviews(args: argparse.Namespace) -> int:
    """Run the review checks in their own process, since they load PyTorch and the detector models."""
    if importlib.util.find_spec("torch") is None:
        raise tools.ToolError("the review checks need PyTorch, which pip install . installs with PeerCheck")
    options = [*_option("--profile", args.profile), *_option("--canaries", args.canaries),
               *_option("--dblp-index", args.dblp_index), *_option("--out", args.out), *_option("--json", args.json)]
    # The double dash keeps a folder whose name starts with a dash from reading as an option.
    return subprocess.call([sys.executable, "-m", "peercheck.reviews", *options, "--", str(args.reviews)])


def run_conflicts(args: argparse.Namespace) -> int:
    """Find conflicts of interest from the author and committee lists and write the report."""
    if not args.authors or not args.pc:
        raise inputs.InputError("--conflicts needs the author list of --authors and the committee list of --pc")
    if args.save_index and (args.dblp_index or not args.dblp_dump):
        raise inputs.InputError("--save-index saves the index built from --dblp-dump; give --dblp-dump without "
                                "--dblp-index")
    venue = profiles.load(args.profile or profiles.DEFAULT)
    out = args.out or Path("conflicts.xlsx")
    authors = inputs.read_people(args.authors, with_paper=True)
    committee = inputs.read_people(args.pc, with_paper=False)
    people = list(dict.fromkeys([person for group in authors.values() for person in group] + committee))
    index = None
    if args.dblp_index:
        index = dblp.load_index(args.dblp_index)
        missing = index.missing(people)
        if missing:
            raise inputs.InputError(f"the dblp index {args.dblp_index} lacks {len(missing)} of the {len(people)} "
                                    f"people of the lists, such as {missing[0].name}; build it again with --dblp-dump "
                                    "and --save-index")
    elif args.dblp_dump:
        index = dblp.build_index(args.dblp_dump, people)
        if args.save_index:
            index.save(args.save_index)
    found = conflicts.find_conflicts(authors, committee, index, venue.options("conflicts"))
    report.write_sheets(out, {"Conflicts": conflicts.rows(found)}, [], [("Profile", venue.name),
                                          ("DBLP", "used" if index is not None else "not used")], key="Paper")
    print(f"{len(found)} possible conflicts. Report: {out}")
    return 0


def run_canary(args: argparse.Namespace) -> int:
    """Write a copy of each submission PDF with its hidden citation and update the key file."""
    if not args.out or not args.canaries:
        raise inputs.InputError("--canary needs the folder of the marked PDFs in --out and the key file in --canaries")
    venue = profiles.load(args.profile or profiles.DEFAULT)
    count, skipped = canary.mark_folder(args.canary, args.out, args.canaries, venue)
    print(f"{count} PDFs marked in {args.out}. Key: {args.canaries}")
    for name in skipped:
        print(f"skipped {name}", file=sys.stderr)
    return 0


def run_setup(args: argparse.Namespace) -> int:
    """Download Hallucinator, the DBLP database, and the Retraction Watch list of the reference check."""
    for path in references.install_tools(tools.cache_dir(), args.dblp_dump, args.retraction_csv, args.refresh):
        print(f"installed {path}")
    return 0


def run_gui(args: argparse.Namespace) -> int:
    """Serve the checks as a page in the browser until Ctrl+C."""
    # The Docker image sets both variables, since a container must listen on every address of a known port.
    host = args.host or _gui_host(os.environ.get("PEERCHECK_GUI_HOST") or "127.0.0.1")
    port = args.port if args.port is not None else _port(os.environ.get("PEERCHECK_GUI_PORT") or "0")
    # The page offers the profile of the session first, therefore a profile that does not load stops here.
    if args.profile:
        profiles.load(args.profile)
    return gui.serve(args.profile, port, not args.no_browser, host)


RUNNERS = {"papers": run_papers, "reviews": run_reviews, "conflicts": run_conflicts, "canary": run_canary,
           "setup": run_setup, "gui": run_gui}

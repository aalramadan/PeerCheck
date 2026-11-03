"""Command line and interactive menu of PeerCheck."""

from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
from pathlib import Path

from peercheck import __version__, canary, conflicts, dblp, inputs, pipeline, report, tools
from peercheck import profile as profiles
from peercheck.checks import references
from peercheck.findings import needs_review

MENU = """
========================================
  PeerCheck {version} ({profile})
========================================
1. Check submission PDFs
2. Check reviews
3. Find conflicts of interest
4. Exit
========================================"""
EXPECTED_ERRORS = (inputs.InputError, profiles.ProfileError, tools.ToolError, ValueError, OSError)


def main(argv: list[str] | None = None) -> int:
    """Run the command given on the command line, or the interactive menu when none is given."""
    args = parser().parse_args(argv)
    if not getattr(args, "command", None):
        return menu(args.profile)
    try:
        return args.handler(args)
    except EXPECTED_ERRORS as exc:
        print(f"peercheck: {exc}", file=sys.stderr)
        return 2


def parser() -> argparse.ArgumentParser:
    """Build the parser of the command line."""
    top = argparse.ArgumentParser(prog="peercheck", description="Screen submissions and reviews locally.")
    top.add_argument("--version", action="version", version=f"PeerCheck {__version__}")
    top.add_argument("--profile", default="icse-2027", help="venue profile key or YAML file (default icse-2027)")
    commands = top.add_subparsers(dest="command")

    papers = commands.add_parser("papers", help="check the submission PDFs of a folder")
    papers.add_argument("pdfs", type=Path, help="folder with the submission PDFs")
    papers.add_argument("--submissions", type=Path, help="submission sheet (EasyChair Excel or HotCRP CSV)")
    papers.add_argument("--authors", type=Path, help="author list with paper, first, last, email, affiliation")
    papers.add_argument("--checks", help=f"comma-separated subset of {', '.join(pipeline.PAPER_CHECKS)}")
    papers.add_argument("--out", type=Path, default=Path("report.xlsx"), help="Excel report (default report.xlsx)")
    papers.add_argument("--json", type=Path, help="also write the results as JSON")
    papers.add_argument("--html", type=Path, help="also write an HTML page for viewing in a browser")
    papers.set_defaults(handler=run_papers)

    reviews = commands.add_parser("reviews", help="check the EasyChair review XML files of a folder",
                                  add_help=False)
    reviews.add_argument("rest", nargs=argparse.REMAINDER, help="arguments of python -m peercheck.reviews")
    reviews.set_defaults(handler=run_reviews)

    found = commands.add_parser("conflicts", help="find conflicts of interest between authors and the committee")
    found.add_argument("--authors", type=Path, required=True, help="author list with paper, first, last, email")
    found.add_argument("--pc", type=Path, help="committee list with first, last, email, affiliation, dblp")
    found.add_argument("--reviewer-csv", type=Path, help="EasyChair reviewer.csv, instead of --pc")
    found.add_argument("--assignment-csv", type=Path, help="EasyChair assignment.csv (needs --reviewer-csv)")
    found.add_argument("--conflict-csv", type=Path, help="EasyChair conflict export (needs --reviewer-csv)")
    found.add_argument("--dblp-dump", type=Path, help="dblp.xml.gz to build a co-author index from")
    found.add_argument("--dblp-index", type=Path, help="index saved by an earlier run, instead of --dblp-dump")
    found.add_argument("--save-index", type=Path, help="save the index built from --dblp-dump here")
    found.add_argument("--years", type=int, help="co-authorship window in years (default 3)")
    found.add_argument("--out", type=Path, default=Path("conflicts.xlsx"), help="Excel report (default conflicts.xlsx)")
    found.set_defaults(handler=run_conflicts)

    marking = commands.add_parser("canary", help="hide a made-up citation in each submission PDF for the canary "
                                                 "check of the reviews")
    marking.add_argument("pdfs", type=Path, help="folder with the submission PDFs")
    marking.add_argument("--out", type=Path, required=True, help="folder for the marked PDFs")
    marking.add_argument("--key", type=Path, required=True, help="CSV key file of the citations, kept private; "
                                                                 "an existing key keeps its citations")
    marking.set_defaults(handler=run_canary)

    setup = commands.add_parser("setup", help="download the tools and models that some checks need")
    setup.add_argument("what", choices=("references", "cocodet", "binoculars", "editlens"), help="what to download")
    setup.add_argument("--dblp-dump", type=Path, help="references: build from this dblp.xml.gz, no download")
    setup.add_argument("--retraction-csv", type=Path, help="references: use this Retraction Watch CSV, no download")
    setup.add_argument("--refresh", action="store_true", help="references: download and build again")
    setup.set_defaults(handler=run_setup)

    commands.add_parser("doctor", help="report missing programs and bundled files").set_defaults(handler=run_doctor)
    commands.add_parser("profiles", help="list the venue profiles").set_defaults(handler=run_profiles)
    commands.add_parser("menu", help="open the interactive menu").set_defaults(handler=lambda a: menu(a.profile))
    return top


def run_papers(args: argparse.Namespace) -> int:
    """Check a folder of submission PDFs and write the report."""
    venue = profiles.load(args.profile)
    checks = [name.strip() for name in args.checks.split(",")] if args.checks else None
    run = pipeline.run_papers(args.pdfs, venue, args.submissions, args.authors, checks)
    report.write_papers(args.out, run, venue, args.submissions)
    if args.json:
        report.write_json(args.json, run)
    if args.html:
        report.write_papers_html(args.html, run)
    flagged = sum(1 for result in run.results if needs_review(result.findings))
    print(f"{len(run.results)} papers checked, {flagged} need review. Report: {args.out}")
    for name in run.unmatched + run.duplicates:
        print(f"skipped {name}; see the Files sheet", file=sys.stderr)
    return 0


def run_reviews(args: argparse.Namespace) -> int:
    """Run the review checks in their own process, since they load PyTorch and the detector models."""
    if importlib.util.find_spec("torch") is None:
        raise tools.ToolError("the review checks need the reviews extra: pip install 'peercheck[reviews]'")
    rest = [arg for arg in args.rest if arg != "--"]
    return subprocess.call([sys.executable, "-m", "peercheck.reviews", "--profile", args.profile, *rest])


def run_conflicts(args: argparse.Namespace) -> int:
    """Find conflicts of interest from the author and committee lists and write the report."""
    venue = profiles.load(args.profile)
    authors = inputs.read_people(args.authors, with_paper=True)
    members = conflicts.read_members(args.reviewer_csv) if args.reviewer_csv else {}
    if args.pc:
        committee = inputs.read_people(args.pc, with_paper=False)
    elif members:
        committee = list(members.values())
    else:
        raise inputs.InputError("give the committee with --pc or --reviewer-csv")
    if (args.assignment_csv or args.conflict_csv) and not members:
        raise inputs.InputError("--assignment-csv and --conflict-csv need --reviewer-csv for the member IDs")
    assignments = conflicts.read_pairs(args.assignment_csv, members) if args.assignment_csv else None
    declared = conflicts.read_pairs(args.conflict_csv, members) if args.conflict_csv else None
    index = None
    if args.dblp_index:
        index = dblp.load_index(args.dblp_index)
    elif args.dblp_dump:
        people = [person for group in authors.values() for person in group] + committee
        index = dblp.build_index(args.dblp_dump, people)
        if args.save_index:
            index.save(args.save_index)
    options = venue.options("conflicts") | ({"coauthor_years": args.years} if args.years else {})
    found = conflicts.find_conflicts(authors, committee, index, assignments, declared, options)
    sheets = {"Conflicts": conflicts.rows(found)}
    if index is not None and assignments:
        sheets["Reviewer Ties"] = conflicts.rows(conflicts.reviewer_ties(assignments, index, options))
    report.write_sheets(args.out, sheets, [], [("Profile", venue.name),
                                               ("DBLP", "used" if index is not None else "not used")], key="Paper")
    print(f"{len(found)} possible conflicts. Report: {args.out}")
    return 0


def run_canary(args: argparse.Namespace) -> int:
    """Write a copy of each submission PDF with its hidden citation and update the key file."""
    count, skipped = canary.mark_folder(args.pdfs, args.out, args.key, profiles.load(args.profile))
    print(f"{count} PDFs marked in {args.out}. Key: {args.key}")
    for name in skipped:
        print(f"skipped {name}", file=sys.stderr)
    return 0


def run_setup(args: argparse.Namespace) -> int:
    """Download the tools or models of one check into the cache."""
    if args.what == "references":
        for path in references.install_tools(tools.cache_dir(), args.dblp_dump, args.retraction_csv, args.refresh):
            print(f"installed {path}")
        return 0
    return run_reviews(argparse.Namespace(profile=args.profile, rest=["setup", args.what]))


def run_doctor(args: argparse.Namespace) -> int:
    """Print each missing program or bundled file with its install hint."""
    problems = tools.missing()
    for name, hint in problems.items():
        print(f"missing {name}: {hint}")
    if importlib.util.find_spec("torch") is None:
        print("review checks off: pip install 'peercheck[reviews]'")
    print("all programs found" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


def run_profiles(args: argparse.Namespace) -> int:
    """Print the key and the name of each shipped venue profile."""
    for key in profiles.available():
        print(f"{key}: {profiles.load(key).name}")
    return 0


def menu(profile_key: str) -> int:
    """Offer the checks in a loop of numbered choices, as the original suite did."""
    actions = {"1": _menu_papers, "2": _menu_reviews, "3": _menu_conflicts}
    while True:
        print(MENU.format(version=__version__, profile=profile_key))
        try:
            choice = input("Enter your choice (1-4): ").strip()
            if choice == "4":
                return 0
            if choice not in actions:
                print("Please enter 1, 2, 3, or 4.")
                continue
            code = main(["--profile", profile_key, *actions[choice]()])
            print("Done." if code == 0 else f"Finished with exit code {code}.")
        except (EOFError, KeyboardInterrupt):
            print()
            return 0


def _ask(prompt: str, default: str) -> str:
    answer = input(f"{prompt} [{default}]: ").strip()
    return answer or default


def _menu_papers() -> list[str]:
    command = ["papers", _ask("Folder of submission PDFs", "submissions")]
    sheet = _ask("Submission sheet (none to skip)", "submissions.xlsx")
    if sheet != "none" and Path(sheet).is_file():
        command += ["--submissions", sheet]
    authors = _ask("Author list (none to skip)", "none")
    if authors != "none":
        command += ["--authors", authors]
    return command + ["--out", _ask("Report file", "report.xlsx")]


def _menu_reviews() -> list[str]:
    return ["reviews", _ask("Folder of review XML files", "reviews"), "--out", _ask("Report file", "reviews.xlsx")]


def _menu_conflicts() -> list[str]:
    command = ["conflicts", "--authors", _ask("Author list", "authors.csv"), "--pc", _ask("Committee list", "pc.csv")]
    dump = _ask("DBLP dump dblp.xml.gz (none to skip)", "none")
    if dump != "none":
        command += ["--dblp-dump", dump]
    return command + ["--out", _ask("Report file", "conflicts.xlsx")]

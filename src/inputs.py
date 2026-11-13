"""Readers of the inputs of PeerCheck: the PDFs of a folder and the CSV files of submissions, people, and reviews."""

from __future__ import annotations

import codecs
import csv
import io
import re
import sys
from dataclasses import dataclass, field
from itertools import chain, repeat
from pathlib import Path

from peercheck.models import Person, Review
from peercheck.profile import Profile, paper_number

# Header names that EasyChair, HotCRP, and the SIGSOFT author CSV use for the same column.
HEADER_ALIASES = {
    "paper": ("paper", "submission", "submission #", "submission id", "paper id", "#", "id"),
    "first": ("first", "first name", "firstname", "given name", "given_name"),
    "last": ("last", "last name", "lastname", "family name", "family_name", "surname"),
    "email": ("email", "e-mail", "email address"),
    "affiliation": ("affiliation", "organization", "organisation", "institution"),
    "dblp": ("dblp", "dblp id", "dblp url", "dblp pid"),
}
# Optional columns, whose header may hold an alias among other words, such as Primary Email or Affiliations.
OPTIONAL_COLUMNS = ("email", "affiliation", "dblp")
# Review fields meant for the program committee only, which never go to the authors: confidential or private fields,
# and fields that name the committee before any author, such as Comments for PC but not Comments for authors and PC.
COMMITTEE_ONLY = re.compile(r"confidential|private|"
                            r"^(?:(?!authors?\b).)*\b(?:program committee|pc|chairs?|ac|area chair)\b", re.IGNORECASE)
# The fixed columns of a HotCRP review CSV export; every other column is a field of the review form.
HOTCRP_COLUMNS = ("paper", "title", "review", "reviewername", "email")
# A score, a number with an optional sign or a letter, with an optional description after a period, such as -2 or
# "3. Weak accept". A short sentence, such as "No questions.", stays text.
SCORE_VALUE = re.compile(r"[-+]?[0-9A-Za-z]{1,2}(\. [^\n]{0,60})?")
EXCEL_SUFFIXES = (".xlsx", ".xlsm", ".xls")
# A paper ID as a spreadsheet may write it, such as 7, #7, 7.0, or 1,234 and 1 234 with a thousands separator.
PAPER_ID = re.compile(r"#?(\d{1,3}(?:[,\s]\d{3})+|\d+)(?:\.0+)?")


class InputError(ValueError):
    """An input file that is missing or lacks a required column."""


@dataclass
class PdfSet:
    """The PDFs of one folder by paper ID, with the IDs that PeerCheck gave and the names of a taken ID."""

    papers: dict[int, Path] = field(default_factory=dict)
    # The file name of each PDF whose name holds no paper number, by the ID that PeerCheck gave the PDF.
    numbered: dict[int, str] = field(default_factory=dict)
    duplicates: list[str] = field(default_factory=list)


def find_pdfs(folder: Path, profile: Profile | None = None) -> PdfSet:
    """Give each PDF of a folder its paper ID, the number in its name, or the next free ID for a name without one."""
    if folder.is_file():
        raise InputError(f"{folder} is a file; give the folder that holds the PDFs")
    if not folder.is_dir():
        raise InputError(f"PDF folder not found: {folder}")
    found = PdfSet()
    unnumbered = []
    # An absolute path keeps a name such as -paper2.pdf from reading as an option of an external tool.
    for path in sorted(folder.resolve().iterdir()):
        # A name that starts with a dot, such as a ._ file that macOS writes beside a copy, holds no paper.
        if not path.is_file() or path.suffix.lower() != ".pdf" or path.name.startswith("."):
            continue
        paper_id = paper_number(path.name, profile.file_pattern if profile else None)
        if paper_id is None:
            unnumbered.append(path)
        elif paper_id in found.papers:
            found.duplicates.append(path.name)
        else:
            found.papers[paper_id] = path
    for paper_id, path in enumerate(unnumbered, start=max(found.papers, default=0) + 1):
        found.papers[paper_id] = path
        found.numbered[paper_id] = path.name
    return found


def read_rows(path: Path) -> list[dict[str, str]]:
    """Read a CSV file into rows keyed by lowercase header."""
    # The header is the first row that holds a value, since a blank row may stand above it.
    rows = [row for row in _csv_rows(_csv_file(path)) if any(row)]
    if not rows:
        return []
    header = [name.lower() for name in rows[0]]
    return [_keyed_row(header, row) for row in rows[1:]]


def read_submissions(path: Path, profile: Profile | None = None) -> dict[int, str]:
    """Return the title of each paper of a submissions file, keyed by the paper ID."""
    rows = read_rows(path)
    override = profile.id_column if profile else None
    id_key = id_column(rows, override)
    if rows and id_key is None:
        wanted = repr(override) if override else "of paper IDs, such as # or ID"
        raise InputError(f"{path.name} has no column {wanted}")
    titles = {}
    for row in rows:
        paper_id = _paper_id(row.get(id_key, ""))
        if paper_id is not None:
            titles[paper_id] = row.get("title", "")
    return titles


def read_people(path: Path, with_paper: bool) -> dict[int, list[Person]] | list[Person]:
    """Read authors keyed by paper ID, or a list of committee members, from a CSV file."""
    rows = read_rows(path)
    columns = _columns(rows, path, with_paper)
    lacking = [key for key in ("email", "affiliation") if key not in columns]
    if lacking:
        print(f"{path.name} has no {' or '.join(lacking)} column; the checks of these people run without it",
              file=sys.stderr)
    if with_paper:
        ids = [_paper_id(row.get(columns["paper"], "")) for row in rows]
        if None in ids:
            raise InputError(f"{path.name}: {ids.count(None)} of {len(ids)} rows have no paper ID in the column "
                             f"{columns['paper']!r}")
        authors: dict[int, list[Person]] = {}
        for paper_id, row in zip(ids, rows):
            authors.setdefault(paper_id, []).append(_person(row, columns))
        return authors
    return [_person(row, columns) for row in rows]


def read_reviews(path: Path) -> list[Review]:
    """Read the reviews of a CSV file, one review per row, in the form of the review export of HotCRP.

    The columns paper and review (the review ID, such as A or 12A) are required, and the columns title,
    reviewername, and email, where the reviewer may be named, are optional. Every other column is a field of the
    review form. A field whose values are all short scores, such as 3 or B, counts as a score. Any other field counts
    as text, and the text fields meant for the program committee stay out of the text for the authors.
    """
    if path.is_dir():
        raise InputError(f"{path} is a folder; --reviews takes the CSV file of the reviews")
    _csv_file(path)
    if path.suffix.lower() != ".csv":
        raise InputError(f"{path.name} is no CSV file; --reviews takes the CSV file of the reviews, whose columns the "
                         "README shows")
    lines = [line for line in _csv_rows(path) if any(line)]
    # The fixed columns may be capitalized, such as Paper, while the fields keep their names for the report.
    header = [name.lower() if name.lower() in HOTCRP_COLUMNS else name for name in lines[0]] if lines else []
    missing = [name for name in ("paper", "review") if name not in header]
    if missing:
        raise InputError(f"{path.name} is no review export: it lacks the column {' and the column '.join(missing)}")
    rows = [_keyed_row(header, line) for line in lines[1:]]
    fields = [name for name in rows[0] if name not in HOTCRP_COLUMNS] if rows else []
    scores = [name for name in fields if any(row[name] for row in rows)
              and all(SCORE_VALUE.fullmatch(row[name]) for row in rows if row[name])]
    reviews = []
    for number, row in enumerate(rows, start=1):
        texts = {name: _clean(row[name]) for name in fields if name not in scores}
        reviews.append(Review(
            review_id=_review_id(row["paper"], row["review"], number),
            paper_id=_paper_id(row["paper"]),
            title=row.get("title", ""),
            source=path.name,
            scores={name: row[name] for name in scores},
            fields=texts,
            author_text="\n\n".join(value for name, value in texts.items() if value and not COMMITTEE_ONLY.search(name)),
            reviewer=_named_person(row.get("reviewername", ""), row.get("email", "")),
        ))
    if not any(review.author_text for review in reviews) and any(len(row["review"].split()) > 1 for row in rows):
        print(f"{path.name}: the column review holds text, while it is meant for the review ID, such as A; put the "
              "text in a column of its own, such as Comments for authors", file=sys.stderr)
    return reviews


def id_column(rows: list[dict[str, str]], override: str | None = None) -> str | None:
    """Return the lowercase name of the column that holds the paper IDs, or None if the file has none."""
    header = list(rows[0]) if rows else []
    if override:
        return override.lower() if override.lower() in header else None
    names = [alias for alias in HEADER_ALIASES["paper"] if alias in header]
    # A title column may be named Paper beside the ID column, such as # in an export of EasyChair.
    names.sort(key=lambda name: sum(_paper_id(row[name]) is None for row in rows))
    return names[0] if names else None


def _columns(rows: list[dict[str, str]], path: Path, with_paper: bool) -> dict[str, str]:
    header = list(rows[0]) if rows else []
    columns = {}
    for key, aliases in HEADER_ALIASES.items():
        names = [alias for alias in aliases if alias in header]
        if not names and key in OPTIONAL_COLUMNS:
            names = [name for name in header if any(alias in name for alias in aliases)]
        if names:
            columns[key] = id_column(rows) if key == "paper" else names[0]
    required = ["first", "last"] + (["paper"] if with_paper else [])
    missing = [key for key in required if key not in columns]
    if missing:
        raise InputError(f"{path.name} lacks the columns {', '.join(missing)}")
    return columns


def _person(row: dict[str, str], columns: dict[str, str]) -> Person:
    return Person(**{key: row.get(column, "") for key, column in columns.items() if key != "paper"})


def _review_id(paper: str, review: str, number: int) -> str:
    # HotCRP writes the paper number and a letter, such as 12A, which other sheets shorten to A. Any other value takes
    # a dash, since 1012 reads as 101-2 or as 10-12.
    letters = review.removeprefix(paper)
    return f"{paper}{letters}" if letters.isalpha() else f"{paper}-{review or number}"


def _csv_file(path: Path) -> Path:
    if not path.is_file():
        raise InputError(f"file not found: {path}")
    if path.suffix.lower() in EXCEL_SUFFIXES:
        raise InputError(f"{path.name} is an Excel file; save it as CSV")
    return path


def _csv_rows(path: Path) -> list[list[str]]:
    text = _csv_text(path)
    # Excel writes a semicolon or a tab between the cells in some languages; the header shows which one.
    header = re.sub(r'"[^"]*"', "", next((line for line in text.splitlines() if line.strip()), ""))
    delimiter = max(",;\t", key=header.count)
    return [[cell.strip() for cell in row] for row in csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)]


def _csv_text(path: Path) -> str:
    raw = path.read_bytes()
    # Excel saves a CSV file in UTF-8 or in the code page of Windows, and Unicode text in UTF-16.
    encodings = ("utf-16",) if raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)) else ("utf-8-sig", "cp1252")
    for encoding in encodings:
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise InputError(f"{path.name} is in an unknown encoding; save it again as CSV UTF-8")


def _keyed_row(header: list[str], row: list[str]) -> dict[str, str]:
    # A row may end early, such as an Excel row whose last cells are empty.
    return {name: value for name, value in zip(header, chain(row, repeat(""))) if name}


def _named_person(name: str, email: str) -> Person | None:
    first, _, last = name.strip().rpartition(" ")
    return Person(first=first, last=last, email=email.strip()) if name.strip() or email.strip() else None


def _paper_id(value) -> int | None:
    match = PAPER_ID.fullmatch(str(value).strip())
    return int(re.sub(r"\D", "", match.group(1))) if match else None


def _clean(text: str) -> str:
    paragraphs = [re.sub(r"[ \t]+", " ", block).strip() for block in re.split(r"\n\s*\n", text)]
    return "\n\n".join(p for p in paragraphs if p)

"""Readers for the exports of EasyChair and HotCRP: PDFs, submission sheets, people lists, and review XML."""

from __future__ import annotations

import codecs
import csv
import io
import re
import sys
import zipfile
from dataclasses import dataclass, field
from itertools import chain, repeat
from pathlib import Path

import defusedxml.ElementTree as SafeET
import openpyxl

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
# A score as HotCRP writes it, a number or a letter, with an optional description after a period, such as
# "3. Weak accept". A short sentence, such as "No questions.", stays text.
SCORE_VALUE = re.compile(r"[0-9A-Za-z]{1,2}(\. [^\n]{0,60})?")
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
    """Read the first visible sheet of an Excel file or a CSV file into rows keyed by lowercase header."""
    if not path.is_file():
        raise InputError(f"file not found: {path}")
    suffix = path.suffix.lower()
    if suffix == ".xls":
        raise InputError(f"{path.name} is an Excel 97-2003 workbook; save it as .xlsx or CSV")
    # The header is the first row that holds a value, since a blank row may stand above it.
    rows = [row for row in (_sheet_rows(path) if suffix in (".xlsx", ".xlsm") else _csv_rows(path)) if any(row)]
    if not rows:
        return []
    header = [name.lower() for name in rows[0]]
    return [_keyed_row(header, row) for row in rows[1:]]


def read_submissions(path: Path, profile: Profile | None = None) -> dict[int, str]:
    """Return the title of each paper of a submission sheet, keyed by the paper ID."""
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
    """Read authors keyed by paper ID, or a list of committee members, from a CSV or Excel file."""
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
    """Read every review of a folder or a file: EasyChair review XML files and HotCRP review CSV exports."""
    if path.is_file():
        return read_hotcrp_reviews(path) if path.suffix.lower() == ".csv" else _xml_reviews(path)
    if not path.is_dir():
        raise InputError(f"reviews not found: {path}")
    reviews = []
    # A folder may also hold other files, such as an author list or the ._ files of macOS, which hold no reviews.
    for file in sorted(p for p in path.iterdir() if p.is_file() and not p.name.startswith(".")):
        if file.suffix.lower() == ".xml":
            reviews.extend(_xml_reviews(file))
        elif file.suffix.lower() == ".csv":
            try:
                reviews.extend(read_hotcrp_reviews(file))
            except InputError:
                print(f"skipped {file.name}, which is no review export", file=sys.stderr)
    return reviews


def read_hotcrp_reviews(path: Path) -> list[Review]:
    """Read the reviews of a HotCRP review CSV export, one review per row.

    HotCRP writes the columns paper, title, review (the paper number and the review letter, such as 12A),
    reviewername and email where the reviewer may be named, and one column per field of the review form. A field
    whose values are all short scores, such as 3 or B, counts as a score. Any other field counts as text, and the
    text fields meant for the program committee stay out of the text for the authors.
    """
    lines = [line for line in _csv_rows(path) if any(line)]
    # The fixed columns may be capitalized, such as Paper, while the fields keep their names for the report.
    header = [name.lower() if name.lower() in HOTCRP_COLUMNS else name for name in lines[0]] if lines else []
    missing = [name for name in ("paper", "review") if name not in header]
    if missing:
        raise InputError(f"{path.name} is no review export: it lacks the column {' and the column '.join(missing)}")
    rows = [_keyed_row(header, line) for line in lines[1:]]
    fields = [name for name in rows[0] if name not in HOTCRP_COLUMNS] if rows else []
    scores = [name for name in fields if all(SCORE_VALUE.fullmatch(row[name]) for row in rows if row[name])]
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


def parse_review(element, source: str, position: int) -> Review:
    """Turn one review element of EasyChair XML into a review; position counts the reviews of the file from 1."""
    scores, texts = {}, {}
    for item in element.findall("field"):
        name = item.get("name", "").strip()
        score, text = item.find("score"), item.find("text")
        if score is not None:
            scores[name] = (score.text or "").strip()
        elif text is not None:
            texts[name] = _clean(text.text or "")
    author_text = "\n\n".join(value for name, value in texts.items() if value and not COMMITTEE_ONLY.search(name))
    return Review(
        review_id=element.get("id", "").strip() or f"{Path(source).stem}-{position}",
        paper_id=_paper_id(element.get("submission", "")),
        title=element.get("title", "").strip(),
        source=source,
        scores=scores,
        fields=texts,
        author_text=author_text,
        reviewer=_reviewer(element.find("reviewer")),
    )


def id_column(rows: list[dict[str, str]], override: str | None = None) -> str | None:
    """Return the lowercase name of the column that holds the paper IDs, or None if the sheet has none."""
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
        if key == "paper":
            # A title column may be named Paper or Submission beside the ID column, such as Paper ID or Submission #.
            names.sort(key=lambda name: sum(_paper_id(row[name]) is None for row in rows))
        if names:
            columns[key] = names[0]
    required = ["first", "last"] + (["paper"] if with_paper else [])
    missing = [key for key in required if key not in columns]
    if missing:
        raise InputError(f"{path.name} lacks the columns {', '.join(missing)}")
    return columns


def _person(row: dict[str, str], columns: dict[str, str]) -> Person:
    return Person(**{key: row.get(column, "") for key, column in columns.items() if key != "paper"})


def _reviewer(element) -> Person | None:
    if element is None:
        return None
    parts = {name: (element.findtext(name) or "").strip() for name in ("first_name", "last_name", "email")}
    if not any(parts.values()):
        return None
    return Person(first=parts["first_name"], last=parts["last_name"], email=parts["email"])


def _xml_reviews(path: Path) -> list[Review]:
    try:
        root = SafeET.parse(path).getroot()
    except SafeET.ParseError as exc:
        raise InputError(f"{path.name} is no readable review XML: {exc}") from exc
    elements = [root] if root.tag == "review" else list(root.iter("review"))
    return [parse_review(element, path.name, position) for position, element in enumerate(elements, start=1)]


def _review_id(paper: str, review: str, number: int) -> str:
    # HotCRP writes the paper number and a letter, such as 12A, which other sheets shorten to A. Any other value takes
    # a dash, since 1012 reads as 101-2 or as 10-12.
    letters = review.removeprefix(paper)
    return f"{paper}{letters}" if letters.isalpha() else f"{paper}-{review or number}"


def _sheet_rows(path: Path) -> list[list[str]]:
    try:
        workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    except (zipfile.BadZipFile, KeyError) as exc:
        raise InputError(f"{path.name} is no readable Excel workbook; save it again as .xlsx without a password, "
                         "or as CSV") from exc
    visible = [sheet for sheet in workbook.worksheets if sheet.sheet_state == "visible"]
    sheet = (visible or workbook.worksheets)[0]
    # Some programs write a wrong size of the sheet, which read-only mode would trust.
    sheet.reset_dimensions()
    rows = [["" if cell is None else str(cell).strip() for cell in row] for row in sheet.iter_rows(values_only=True)]
    workbook.close()
    return rows


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

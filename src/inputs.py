"""Readers for the exports of EasyChair and HotCRP: PDFs, submission sheets, people lists, and review XML."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path

import defusedxml.ElementTree as SafeET
import openpyxl

from peercheck.models import Person, Review
from peercheck.profile import Profile

# Header names that EasyChair, HotCRP, and the SIGSOFT author CSV use for the same column.
HEADER_ALIASES = {
    "paper": ("paper", "submission", "submission #", "submission id", "paper id", "#", "id"),
    "first": ("first", "first name", "firstname", "given name"),
    "last": ("last", "last name", "lastname", "family name", "surname"),
    "email": ("email", "e-mail", "email address"),
    "affiliation": ("affiliation", "organization", "organisation", "institution"),
    "dblp": ("dblp", "dblp id", "dblp url", "dblp pid"),
}
# Review fields meant for the program committee only, which never go to the authors.
COMMITTEE_ONLY = re.compile(r"confidential|program committee|\bpc\b|chairs? only", re.IGNORECASE)
# The fixed columns of a HotCRP review CSV export; every other column is a field of the review form.
HOTCRP_COLUMNS = ("paper", "title", "review", "reviewername", "email")
# A score as HotCRP writes it, a number or a letter, with an optional description such as "3. Weak accept".
SCORE_VALUE = re.compile(r"[0-9A-Za-z]{1,2}(\.? [^\n]{0,60})?")


class InputError(ValueError):
    """An input file that is missing or lacks a required column."""


@dataclass
class PdfSet:
    """The PDFs of one folder matched to paper IDs, with the names that matched no ID or a taken ID."""

    papers: dict[int, Path] = field(default_factory=dict)
    unmatched: list[str] = field(default_factory=list)
    duplicates: list[str] = field(default_factory=list)


def find_pdfs(folder: Path, profile: Profile) -> PdfSet:
    """Match each PDF of a folder to a paper ID through the file pattern of the profile."""
    if not folder.is_dir():
        raise InputError(f"PDF folder not found: {folder}")
    found = PdfSet()
    for path in sorted(folder.iterdir()):
        if not path.is_file() or path.suffix.lower() != ".pdf":
            continue
        paper_id = profile.paper_id(path.name)
        if paper_id is None:
            found.unmatched.append(path.name)
        elif paper_id in found.papers:
            found.duplicates.append(path.name)
        else:
            found.papers[paper_id] = path
    return found


def read_rows(path: Path) -> list[dict[str, str]]:
    """Read the first sheet of an Excel file or a CSV file into rows keyed by lowercase header."""
    if not path.is_file():
        raise InputError(f"file not found: {path}")
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
        sheet = workbook.worksheets[0]
        rows = [["" if cell is None else str(cell).strip() for cell in row] for row in sheet.iter_rows(values_only=True)]
        workbook.close()
    else:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            rows = [[cell.strip() for cell in row] for row in csv.reader(handle)]
    if not rows:
        return []
    header = [name.lower() for name in rows[0]]
    return [dict(zip(header, row)) for row in rows[1:] if any(row)]


def read_submissions(path: Path, profile: Profile) -> dict[int, str]:
    """Return the title of each paper of a submission sheet, keyed by the ID column of the profile."""
    rows = read_rows(path)
    id_key = profile.id_column.lower()
    if rows and id_key not in rows[0]:
        raise InputError(f"{path.name} has no column {profile.id_column!r}; set id_column in the profile")
    titles = {}
    for row in rows:
        paper_id = _paper_id(row.get(id_key, ""))
        if paper_id is not None:
            titles[paper_id] = row.get("title", "")
    return titles


def read_people(path: Path, with_paper: bool) -> dict[int, list[Person]] | list[Person]:
    """Read authors keyed by paper ID, or a list of committee members, from a CSV or Excel file."""
    rows = read_rows(path)
    columns = _columns(rows[0].keys() if rows else [], path, with_paper)
    if with_paper:
        authors: dict[int, list[Person]] = {}
        for row in rows:
            paper_id = _paper_id(row.get(columns["paper"], ""))
            if paper_id is not None:
                authors.setdefault(paper_id, []).append(_person(row, columns))
        return authors
    return [_person(row, columns) for row in rows]


def read_reviews(path: Path) -> list[Review]:
    """Read every review of a folder or a file: EasyChair review XML files and HotCRP review CSV exports."""
    if path.is_file():
        files = [path]
    elif path.is_dir():
        # A folder may also hold other CSV files, such as an author list, which are no review exports.
        files = sorted(p for p in path.iterdir()
                       if p.suffix.lower() == ".xml" or (p.suffix.lower() == ".csv" and _is_review_export(p)))
    else:
        raise InputError(f"reviews not found: {path}")
    reviews = []
    for file in files:
        if file.suffix.lower() == ".csv":
            reviews.extend(read_hotcrp_reviews(file))
            continue
        root = SafeET.parse(file).getroot()
        elements = [root] if root.tag == "review" else list(root.iter("review"))
        reviews.extend(parse_review(element, file.name) for element in elements)
    return reviews


def read_hotcrp_reviews(path: Path) -> list[Review]:
    """Read the reviews of a HotCRP review CSV export, one review per row.

    HotCRP writes the columns paper, title, review (the review ID within the paper, such as A), reviewername and
    email where the reviewer may be named, and one column per field of the review form. A field whose values are
    all short scores, such as 3 or B, counts as a score. Any other field counts as text, and the text fields meant
    for the program committee stay out of the text for the authors.
    """
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = [{key.strip(): (value or "").strip() for key, value in row.items() if key} for row in csv.DictReader(handle)]
    if not rows or "paper" not in rows[0]:
        raise InputError(f"{path} is no HotCRP review export: it needs the column paper")
    fields = [name for name in rows[0] if name not in HOTCRP_COLUMNS]
    scores = [name for name in fields if all(SCORE_VALUE.fullmatch(row[name]) for row in rows if row[name])]
    reviews = []
    for number, row in enumerate(rows, start=1):
        texts = {name: _clean(row[name]) for name in fields if name not in scores}
        reviews.append(Review(
            review_id=f"{row['paper']}{row.get('review') or f'-{number}'}",
            paper_id=_paper_id(row["paper"]),
            title=row.get("title", ""),
            source=path.name,
            scores={name: row[name] for name in scores},
            fields=texts,
            author_text="\n\n".join(value for name, value in texts.items() if value and not COMMITTEE_ONLY.search(name)),
            reviewer=_named_person(row.get("reviewername", ""), row.get("email", "")),
        ))
    return reviews


def parse_review(element, source: str) -> Review:
    """Turn one review element of EasyChair XML into a review."""
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
        review_id=element.get("id", "").strip() or source,
        paper_id=_paper_id(element.get("submission", "")),
        title=element.get("title", "").strip(),
        source=source,
        scores=scores,
        fields=texts,
        author_text=author_text,
        reviewer=_reviewer(element.find("reviewer")),
    )


def _columns(header, path: Path, with_paper: bool) -> dict[str, str]:
    present = set(header)
    columns = {}
    for key, aliases in HEADER_ALIASES.items():
        match = next((alias for alias in aliases if alias in present), None)
        if match:
            columns[key] = match
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


def _is_review_export(path: Path) -> bool:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        header = {name.strip().lower() for name in next(csv.reader(handle), [])}
    return {"paper", "review"} <= header


def _named_person(name: str, email: str) -> Person | None:
    first, _, last = name.strip().rpartition(" ")
    return Person(first=first, last=last, email=email.strip()) if name.strip() or email.strip() else None


def _paper_id(value) -> int | None:
    text = str(value).strip().removesuffix(".0")
    return int(text) if text.isdigit() else None


def _clean(text: str) -> str:
    paragraphs = [re.sub(r"[ \t]+", " ", block).strip() for block in re.split(r"\n\s*\n", text)]
    return "\n\n".join(p for p in paragraphs if p)

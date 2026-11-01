"""Retraction Watch notices for the DOIs of a reference list, read from the CSV that Crossref publishes."""

from __future__ import annotations

import csv
import functools
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote

# Crossref serves the Retraction Watch database here, updated each working day.
CSV_URL = "https://gitlab.com/crossref/retraction-watch-data/-/raw/main/retraction_watch.csv"
# Natures that cast doubt on a cited work. A Correction never does, and a later Reinstatement lifts the doubt.
CONCERNS = ("Retraction", "Expression of concern")
REINSTATEMENT = "Reinstatement"
DOI_PREFIX = re.compile(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", re.IGNORECASE)


@dataclass(frozen=True)
class Notice:
    """One Retraction Watch notice on one original paper, with its date as YYYY-MM-DD."""

    doi: str
    nature: str
    reason: str
    date: str
    notice_doi: str = ""


def normalize_doi(text: str) -> str:
    """Return a DOI in lowercase without a resolver prefix, or an empty string if the text holds no DOI."""
    doi = unquote(DOI_PREFIX.sub("", text.strip())).rstrip(".,;").lower()
    return doi if doi.startswith("10.") and "/" in doi else ""


def load(path: Path) -> dict[str, tuple[Notice, ...]]:
    """Index the notices of retraction_watch.csv by the DOI of the original paper, once per file version."""
    stat = path.stat()
    return _load(str(path), stat.st_mtime_ns, stat.st_size)


def match(dois: Iterable[str], index: dict[str, tuple[Notice, ...]]) -> dict[str, tuple[Notice, ...]]:
    """Return the notices of each DOI of a reference list that the index holds, keyed by the normalized DOI."""
    found = {}
    for doi in dois:
        key = normalize_doi(doi)
        if key in index:
            found[key] = index[key]
    return found


def in_force(notices: Iterable[Notice]) -> Notice | None:
    """Return the newest retraction or expression of concern, or None if none exists or a reinstatement followed."""
    relevant = [n for n in notices if n.nature in CONCERNS or n.nature == REINSTATEMENT]
    if not relevant:
        return None
    # On the same date a retraction outranks an expression of concern, and both outrank a reinstatement.
    rank = {REINSTATEMENT: 0, CONCERNS[1]: 1, CONCERNS[0]: 2}
    newest = max(relevant, key=lambda n: (n.date, rank[n.nature]))
    return None if newest.nature == REINSTATEMENT else newest


@functools.lru_cache(maxsize=2)
def _load(path: str, _mtime_ns: int, _size: int) -> dict[str, tuple[Notice, ...]]:
    index: dict[str, list[Notice]] = {}
    try:
        with open(path, encoding="utf-8", errors="replace", newline="") as handle:
            for row in csv.DictReader(handle):
                doi = normalize_doi(row.get("OriginalPaperDOI") or "")
                if doi:
                    index.setdefault(doi, []).append(Notice(
                        doi=doi,
                        nature=(row.get("RetractionNature") or "").strip(),
                        reason=(row.get("Reason") or "").strip().strip(";").replace(";", "; "),
                        date=_iso_date(row.get("RetractionDate") or ""),
                        notice_doi=normalize_doi(row.get("RetractionDOI") or ""),
                    ))
    except csv.Error as exc:
        raise ValueError(f"{path} is no valid CSV file ({exc})") from exc
    return {doi: tuple(notices) for doi, notices in index.items()}


def _iso_date(text: str) -> str:
    day = text.strip().split(" ")[0]
    try:
        return datetime.strptime(day, "%m/%d/%Y").date().isoformat()
    except ValueError:
        return day

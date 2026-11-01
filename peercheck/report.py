"""Excel and JSON reports of the paper checks and the review checks."""

from __future__ import annotations

import csv
import datetime
import json
from dataclasses import asdict
from pathlib import Path

import openpyxl
from openpyxl.utils import get_column_letter

from peercheck import __version__
from peercheck.checks.layout import REPORT_COLUMNS
from peercheck.findings import Finding, Severity, count, needs_review
from peercheck.pipeline import PapersRun
from peercheck.profile import Profile

SUMMARY_COLUMNS = ("Errors", "Warnings", "Needs Review", "Findings")
FINDING_COLUMNS = ("Check", "Severity", "Page", "Message", "Evidence")
# A text cell that starts with one of these would run as a formula in a spreadsheet program.
FORMULA_START = ("=", "+", "-", "@")


def write_papers(out: Path, run: PapersRun, profile: Profile, submissions: Path | None = None) -> None:
    """Write the Excel report of a paper run, extending the submission sheet when one is given."""
    workbook, sheet, id_column = _papers_sheet(submissions, profile)
    header = [cell.value for cell in sheet[1]]
    first_new = len(header) + 1
    for offset, name in enumerate(REPORT_COLUMNS + SUMMARY_COLUMNS):
        _set(sheet.cell(row=1, column=first_new + offset), name)
    rows = _rows_by_id(sheet, id_column)
    by_id = {result.paper.paper_id: result for result in run.results}
    for paper_id, result in by_id.items():
        row = rows.get(paper_id)
        if row is None:
            row = sheet.max_row + 1
            _set(sheet.cell(row=row, column=id_column), paper_id)
        metrics = result.layout.row() if result.layout else {}
        values = [metrics.get(name) for name in REPORT_COLUMNS] + [
            count(result.findings, Severity.ERROR),
            count(result.findings, Severity.WARNING),
            "yes" if needs_review(result.findings) else "no",
            "\n".join(f.as_text() for f in result.findings if f.severity is not Severity.INFO),
        ]
        for offset, value in enumerate(values):
            _set(sheet.cell(row=row, column=first_new + offset), value)
    for paper_id, row in rows.items():
        if paper_id not in by_id:
            _set(sheet.cell(row=row, column=first_new + len(REPORT_COLUMNS) + 3), "WARNING: missing PDF")
    _findings_sheet(workbook, "Paper Findings", "Paper",
                    [(r.paper.paper_id, f) for r in run.results for f in r.findings])
    files = workbook.create_sheet("Files")
    _append(files, ("File", "Problem"))
    for name in run.unmatched:
        _append(files, (name, "the name holds no paper ID for this profile"))
    for name in run.duplicates:
        _append(files, (name, "another PDF has the same paper ID; this one was skipped"))
    _about(workbook, profile, [("Checks run", ", ".join(run.checks))])
    _save(workbook, out)


def write_sheets(out: Path, sheets: dict[str, list[dict]], findings: list[tuple[object, Finding]],
                 about: list[tuple[str, str]], key: str = "Review") -> None:
    """Write sheets of rows, a sheet of findings keyed by owner, and an About sheet to one workbook."""
    workbook = openpyxl.Workbook()
    workbook.remove(workbook.active)
    for title, rows in sheets.items():
        sheet = workbook.create_sheet(title)
        columns = list(dict.fromkeys(name for row in rows for name in row))
        _append(sheet, columns or ("No rows",))
        for row in rows:
            _append(sheet, [row.get(name) for name in columns])
    _findings_sheet(workbook, f"{key} Findings", key, findings)
    sheet = workbook.create_sheet("About")
    for row in [("PeerCheck version", __version__), ("Created", datetime.date.today().isoformat())] + about:
        _append(sheet, row)
    _save(workbook, out)


def write_json(out: Path, data: object) -> None:
    """Write any result as JSON, turning dataclasses, paths, and enums into plain values."""
    out.write_text(json.dumps(_plain(data), indent=2, ensure_ascii=False), encoding="utf-8")


def _papers_sheet(submissions: Path | None, profile: Profile):
    id_name = profile.id_column.lower()
    if submissions and submissions.suffix.lower() in (".xlsx", ".xlsm"):
        workbook = openpyxl.load_workbook(submissions)
        sheet = workbook.worksheets[0]
        header = [str(cell.value or "").strip().lower() for cell in sheet[1]]
        if id_name in header:
            workbook.active = 0
            return workbook, sheet, header.index(id_name) + 1
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Papers"
    if submissions and submissions.suffix.lower() == ".csv":
        with submissions.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.reader(handle))
        header = [name.strip().lower() for name in rows[0]] if rows else []
        if id_name in header:
            for row in rows:
                _append(sheet, row)
            return workbook, sheet, header.index(id_name) + 1
    _append(sheet, ("Paper",))
    return workbook, sheet, 1


def _rows_by_id(sheet, id_column: int) -> dict[int, int]:
    rows = {}
    for row in range(2, sheet.max_row + 1):
        text = str(sheet.cell(row=row, column=id_column).value or "").strip().removesuffix(".0")
        if text.isdigit():
            rows.setdefault(int(text), row)
    return rows


def _findings_sheet(workbook, title: str, key: str, items: list[tuple[object, Finding]]) -> None:
    sheet = workbook.create_sheet(title)
    _append(sheet, (key,) + FINDING_COLUMNS)
    for owner, finding in items:
        _append(sheet, (owner, finding.check, finding.severity.value, finding.page, finding.message, finding.evidence))


def _about(workbook, profile: Profile, extra: list[tuple[str, str]]) -> None:
    sheet = workbook.create_sheet("About")
    for row in [("PeerCheck version", __version__), ("Profile", profile.name), ("Rules", profile.source),
                ("Created", datetime.date.today().isoformat())] + extra:
        _append(sheet, row)


def _append(sheet, values) -> None:
    row = sheet.max_row + 1 if sheet.max_row > 1 or sheet.cell(row=1, column=1).value is not None else 1
    for column, value in enumerate(values, start=1):
        _set(sheet.cell(row=row, column=column), value)


def _set(cell, value) -> None:
    cell.value = value
    if isinstance(value, str) and value.startswith(FORMULA_START):
        cell.data_type = "s"


def _save(workbook, out: Path) -> None:
    for sheet in workbook.worksheets:
        for column in range(1, sheet.max_column + 1):
            letter = get_column_letter(column)
            if sheet.column_dimensions[letter].width in (None, 13.0):
                sheet.column_dimensions[letter].width = 18
    out.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(out)


def _plain(value):
    if hasattr(value, "__dataclass_fields__"):
        return _plain(asdict(value))
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Severity):
        return value.value
    return value

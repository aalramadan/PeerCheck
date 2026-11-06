"""Excel and JSON reports of the paper checks and the review checks."""

from __future__ import annotations

import csv
import datetime
import html
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
HTML_STYLE = """
:root{--bg:#ffffff;--fg:#1f2328;--muted:#59636e;--line:#d1d9e0;--head:#f6f8fa;--error:#cf222e;--warning:#9a6700;
--info:#59636e;--clear:#1a7f37;color-scheme:light}
:root[data-theme=dark]{--bg:#0d1117;--fg:#e6edf3;--muted:#9198a1;--line:#3d444d;--head:#151b23;--error:#f85149;
--warning:#d29922;--info:#9198a1;--clear:#3fb950;color-scheme:dark}
body{font-family:system-ui,sans-serif;margin:2rem;color:var(--fg);background:var(--bg)}
h1{font-size:1.4rem;margin:0 0 .3rem}
.meta{color:var(--muted);margin:0 0 1rem}
.controls{display:flex;gap:1rem;align-items:center;margin-bottom:1rem}
input[type=search]{padding:.3rem .5rem;min-width:16rem}
table{border-collapse:collapse;width:100%;font-size:.9rem}
th,td{border:1px solid var(--line);padding:.35rem .5rem;text-align:left;vertical-align:top}
td:not(:last-child){white-space:nowrap}
th{background:var(--head);position:sticky;top:0}
tr.flagged td:first-child{border-left:4px solid var(--error)}
tr.clear td:first-child{border-left:4px solid var(--clear)}
ul{margin:.4rem 0;padding-left:1.1rem}
li{margin:.25rem 0}
.badge{display:inline-block;min-width:4.2rem;padding:0 .3rem;border-radius:.6rem;color:#fff;font-size:.75rem;text-align:center}
li.error .badge{background:var(--error)}li.warning .badge{background:var(--warning)}li.info .badge{background:var(--info)}
.evidence{color:var(--muted);font-family:ui-monospace,monospace;font-size:.8rem;white-space:pre-wrap;word-break:break-word}
.notes{margin-top:1rem;color:var(--muted)}
"""
HTML_SCRIPT = """
const root=document.documentElement,theme=document.getElementById('theme');
root.dataset.theme=localStorage.getItem('peercheck-theme')||(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light');
theme.addEventListener('click',()=>{root.dataset.theme=root.dataset.theme==='dark'?'light':'dark';
localStorage.setItem('peercheck-theme',root.dataset.theme);});
const q=document.getElementById('q'),only=document.getElementById('only'),sev=document.getElementById('sev');
function apply(){const t=q.value.toLowerCase();for(const r of document.querySelectorAll('tbody tr')){
r.hidden=!((!t||r.textContent.toLowerCase().includes(t))&&(!only.checked||r.classList.contains('flagged'))
&&(!sev.value||r.dataset.sev.split(' ').includes(sev.value)));}}
[q,only,sev].forEach(e=>e.addEventListener('input',apply));
"""
# The page leaves out file names and paper titles, which can identify a submission.
HIDDEN_COLUMNS = ("Findings", "Needs Review", "Source File", "Title")
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


def write_papers_html(out: Path, run: PapersRun) -> None:
    """Write a self-contained HTML page of a paper run for viewing in a browser."""
    columns = ("Paper", "Main Pages", "Reference-only Pages", "Paper Size (pt)", "Errors", "Warnings")
    records = []
    for result in run.results:
        metrics = result.layout.row() if result.layout else {}
        records.append(([result.paper.paper_id, metrics.get("Main Pages"),
                         metrics.get("Reference-only Pages"), metrics.get("Paper Size (height x width, pt)"),
                         count(result.findings, Severity.ERROR), count(result.findings, Severity.WARNING)],
                        result.findings))
    notes = ([f"Paper {paper_id} has no PDF." for paper_id in run.missing_pdfs]
             + [f"{name} holds no paper ID." for name in run.unmatched]
             + [f"{name} repeats a paper ID and was skipped." for name in run.duplicates])
    _write_html(out, "PeerCheck, Papers", columns, records, notes + [f"Checks run: {', '.join(run.checks)}."])


def write_rows_html(out: Path, title: str, rows: list[dict], findings: dict[str, list[Finding]], key: str,
                    leave_out: tuple[str, ...] = ()) -> None:
    """Write a self-contained HTML page of rows with their findings, such as one row per review.

    The columns in leave_out stay in the workbook and the JSON file but not on the page.
    """
    skip = HIDDEN_COLUMNS + leave_out
    columns = tuple(dict.fromkeys(name for row in rows for name in row
                                  if name not in skip and any(r.get(name) not in (None, "") for r in rows)))
    records = [([row.get(name) for name in columns], findings.get(str(row.get(key)), [])) for row in rows]
    _write_html(out, title, columns, records, [])


def write_json(out: Path, data: object) -> None:
    """Write any result as JSON, turning dataclasses, paths, and enums into plain values."""
    out.write_text(json.dumps(_plain(data), indent=2, ensure_ascii=False), encoding="utf-8")


def _write_html(out: Path, title: str, columns, records, notes: list[str]) -> None:
    rows = []
    for cells, findings in records:
        items = "".join(
            f'<li class="{f.severity.value}"><span class="badge">{f.severity.value}</span> <code>{_e(f.check)}</code> '
            f"{_e(f.message)}{f' (page {f.page})' if f.page else ''}"
            f"{f'<div class=evidence>{_e(f.evidence)}</div>' if f.evidence else ''}</li>" for f in findings)
        detail = f"<details><summary>{len(findings)} finding(s)</summary><ul>{items}</ul></details>" if findings else ""
        severities = " ".join(sorted({f.severity.value for f in findings}))
        state = "flagged" if needs_review(findings) else "clear"
        rows.append(f'<tr class="{state}" data-sev="{severities}">' + "".join(f"<td>{_e(c)}</td>" for c in cells)
                    + f"<td>{detail}</td></tr>")
    flagged = sum(1 for _, findings in records if needs_review(findings))
    header = "".join(f"<th>{_e(c)}</th>" for c in columns) + "<th>Findings</th>"
    page = (f'<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>{_e(title)}</title>'
            f"<style>{HTML_STYLE}</style></head><body><h1>{_e(title)}</h1>"
            f'<p class="meta">{len(records)} rows, {flagged} need review. PeerCheck {__version__}, '
            f"{datetime.date.today().isoformat()}.</p>"
            '<div class="controls"><input id="q" type="search" placeholder="Filter rows">'
            '<label><input id="only" type="checkbox"> Needs review only</label><select id="sev">'
            '<option value="">All severities</option><option>error</option><option>warning</option>'
            '<option>info</option></select><button id="theme" type="button">Light or dark</button></div>'
            f"<table><thead><tr>{header}</tr></thead><tbody>{''.join(rows)}</tbody></table>"
            + "".join(f'<p class="notes">{_e(note)}</p>' for note in notes)
            + f"<script>{HTML_SCRIPT}</script></body></html>")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")


def _e(value) -> str:
    return "" if value is None else html.escape(str(value))


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

"""CSV files and HTML pages of the paper checks, the review checks, and the conflict check."""

from __future__ import annotations

import csv
import datetime
import html
import re
from pathlib import Path

from peercheck import __version__
from peercheck.findings import Finding, Severity, count, needs_review
from peercheck.inputs import EXCEL_SUFFIXES
from peercheck.papers.layout import REPORT_COLUMNS
from peercheck.papers.pipeline import PapersRun

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
FORMULA_START = ("=", "+", "-", "@", "\t", "\r")
NUMBER = re.compile(r"[-+]?\d+(?:\.\d+)?")
# Control characters other than the tab and the line breaks, such as U+000E from the text of a PDF.
CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
CONFLICT_COLUMNS = ("Paper", "PC member", "With", "Kinds")


def paper_rows(run: PapersRun) -> list[dict]:
    """Return one row per paper of a run with its measurements and findings, and one per listed paper without a PDF."""
    rows = []
    for result in run.results:
        metrics = result.layout.row() if result.layout else {}
        rows.append({"Paper": result.paper.paper_id, **({"Title": result.paper.title} if run.titles else {}),
                     **{name: metrics.get(name) for name in REPORT_COLUMNS},
                     "Errors": count(result.findings, Severity.ERROR),
                     "Warnings": count(result.findings, Severity.WARNING),
                     "Needs Review": "yes" if needs_review(result.findings) else "no",
                     "Findings": findings_text(result.findings)})
    for paper_id in run.missing_pdfs:
        missing = Finding("input.missing-pdf", Severity.WARNING, "the submissions file lists the paper, which has no PDF")
        rows.append({"Paper": paper_id, "Title": run.titles.get(paper_id, ""), "Errors": 0, "Warnings": 1,
                     "Needs Review": "yes", "Findings": missing.as_text()})
    return rows


def findings_text(findings: list[Finding]) -> str:
    """Return the findings as the text of one cell, one finding per line with its evidence in brackets."""
    return "\n".join(f.as_text() + (f" [{' '.join(f.evidence.split())}]" if f.evidence else "") for f in findings)


def csv_path(out: Path | None, default: str, *sources: Path | None) -> Path:
    """Return the path of a CSV report, refusing an Excel name and the path of an input file."""
    path = out or Path(default)
    if path.suffix.lower() in EXCEL_SUFFIXES:
        raise ValueError(f"--out names the CSV file of the report, such as {default}")
    for source in sources:
        if source is not None and path.resolve() == Path(source).resolve():
            raise ValueError(f"--out {path} would overwrite the input {source}; choose another file")
    return path


def write_csv(out: Path, rows: list[dict]) -> None:
    """Write rows to a CSV file whose header holds every column of the rows, in the order of first use."""
    columns = list(dict.fromkeys(name for row in rows for name in row))
    out.parent.mkdir(parents=True, exist_ok=True)
    # The byte order mark lets Excel open the file as UTF-8.
    with out.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(columns or ["No rows"])
        for row in rows:
            writer.writerow([_cell(row.get(name)) for name in columns])


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
    notes = [f"Paper {paper_id} has no PDF." for paper_id in run.missing_pdfs]
    if run.numbered:
        notes.append(f"Numbered {len(run.numbered)} PDF(s) whose names hold no paper number; the messages of the run "
                     "name them.")
    if run.duplicates:
        notes.append(f"Skipped {len(run.duplicates)} PDF(s) that repeat a paper number; the messages of the run name "
                     "them.")
    _write_html(out, "PeerCheck, Papers", columns, records, notes + [f"Checks run: {', '.join(run.checks)}."])


def write_rows_html(out: Path, title: str, rows: list[dict], findings: dict[str, list[Finding]], key: str,
                    leave_out: tuple[str, ...] = (), notes: list[str] | None = None) -> None:
    """Write a self-contained HTML page of rows with their findings, such as one row per review.

    The columns in leave_out stay in the CSV file but not on the page. The notes follow the table.
    """
    skip = HIDDEN_COLUMNS + leave_out
    columns = tuple(dict.fromkeys(name for row in rows for name in row
                                  if name not in skip and any(r.get(name) not in (None, "") for r in rows)))
    records = [([row.get(name) for name in columns], findings.get(str(row.get(key)), [])) for row in rows]
    _write_html(out, title, columns, records, list(notes or []))


def write_conflicts_html(out: Path, rows: list[dict], notes: list[str]) -> None:
    """Write a self-contained HTML page of the conflicts, one row per conflict with its reasons as findings."""
    records = [([row.get(name) for name in CONFLICT_COLUMNS],
                [Finding("conflict", Severity.WARNING, reason) for reason in str(row.get("Reasons") or "").splitlines()])
               for row in rows]
    _write_html(out, "PeerCheck, Conflicts of interest", CONFLICT_COLUMNS, records, notes)


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


def _cell(value):
    if value is None:
        return ""
    if not isinstance(value, str):
        return value
    value = CONTROL.sub("", value)
    # An apostrophe before such a text keeps a spreadsheet program from running it as a formula.
    return "'" + value if value.startswith(FORMULA_START) and not NUMBER.fullmatch(value) else value

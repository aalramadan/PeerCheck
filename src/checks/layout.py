"""Format check of a submission PDF with banal, the format analyzer of HotCRP.

banal reports the paper size, the margins, the columns, the fonts, the headings, and a type for each page
(body, bib, appendix, figure, or blank). This module turns that report into page counts and checks them
against the format rules of the venue profile. Pages that banal types as bib from the start of the
references on count as reference-only pages, and every other page counts toward the main text, as in the
ICSME 2026 rule of 10 pages plus up to 2 pages that contain only references.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from peercheck import tools
from peercheck.findings import Finding, Severity
from peercheck.models import Paper
from peercheck.profile import FormatRules, Profile

BANAL_TIMEOUT = 300
REFERENCES = re.compile(r"^(references|bibliography|r e f e r e n c e s)$")
NUMBERING = re.compile(r"^\s*(?:[ivxlcdm]+|\d+(?:\.\d+)*|[a-z])[.)]?\s+", re.IGNORECASE)
ABSTRACT = re.compile(r"\babstract\b", re.IGNORECASE)
# Fewer words per page than this marks slides, scans, or a draft; banal counts about 900 on an IEEE page.
MIN_WORDS_PER_PAGE = 150
# A paper this long with no references section is likely missing its bibliography.
MIN_PAGES_WITH_REFERENCES = 6
REPORT_COLUMNS = (
    "Total Pages", "Main Pages", "Reference-only Pages", "References Start Page", "Blank Pages",
    "Appendix Pages", "Figure Pages", "Words", "Characters", "Body Font (pt)", "Reference Font (pt)",
    "Line Spacing (pt)", "Margins (top, right, bottom, left)", "Columns", "Paper Size (height x width, pt)",
    "Page Number Margin",
)


class BanalError(RuntimeError):
    """banal could not read a PDF."""


@dataclass
class Layout:
    """The page counts and the measures that banal gives for one PDF."""

    total_pages: int = 0
    main_pages: int = 0
    reference_pages: int = 0
    references_start: int | None = None
    blank_pages: int = 0
    appendix_pages: int = 0
    figure_pages: int = 0
    words: int = 0
    characters: int = 0
    body_font: float | None = None
    reference_font: float | None = None
    leading: float | None = None
    margins: tuple[float, ...] | None = None
    columns: int | None = None
    paper_size: tuple[float, float] | None = None
    page_number_margin: float | None = None
    mixed_paper_sizes: bool = False
    headings: list[str] = field(default_factory=list)

    def row(self) -> dict[str, object]:
        """Return the measures under the report column names."""
        values = (
            self.total_pages, self.main_pages, self.reference_pages, self.references_start, self.blank_pages,
            self.appendix_pages, self.figure_pages, self.words, self.characters, self.body_font,
            self.reference_font, self.leading, _join(self.margins), self.columns,
            None if self.paper_size is None else f"{self.paper_size[0]:g} x {self.paper_size[1]:g}",
            self.page_number_margin,
        )
        return dict(zip(REPORT_COLUMNS, values))


@dataclass
class LayoutResult:
    """The layout of one PDF, if banal could read it, and the findings of the format rules."""

    layout: Layout | None
    findings: list[Finding]


def run_banal(pdf: Path) -> dict:
    """Run banal on a PDF and return its JSON report, or raise BanalError."""
    command = [tools.program("perl"), str(tools.banal()), "-json", "-pagenum", "-no-time", str(pdf)]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=BANAL_TIMEOUT, check=False)
    except subprocess.TimeoutExpired as exc:
        raise BanalError(f"banal timed out after {BANAL_TIMEOUT} s") from exc
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError:
        report = None
    if result.returncode != 0 or not isinstance(report, dict) or report.get("error"):
        message = next((line.strip() for line in result.stderr.splitlines() if line.strip()), "no output")
        raise BanalError(message.replace(str(pdf), pdf.name))
    return report


def measure(report: dict) -> Layout:
    """Turn a banal JSON report into page counts and measures."""
    pages = report.get("pages") or []
    layout = Layout(total_pages=len(pages))
    for number, page in enumerate(pages, start=1):
        names = [_normalize(h) for h in page.get("headings", [])]
        layout.headings.extend(names)
        if layout.references_start is None and any(REFERENCES.match(name) for name in names):
            layout.references_start = number
    if layout.references_start is None:
        layout.references_start = next((n for n, p in enumerate(pages, 1) if p.get("type") == "bib"), None)
    if layout.references_start is None:
        layout.references_start = next((n for n, p in enumerate(pages, 1) if "reffontsize" in p), None)
    start = layout.references_start or len(pages) + 1
    layout.reference_pages = sum(1 for n, p in enumerate(pages, 1) if n >= start and p.get("type") == "bib")
    layout.main_pages = layout.total_pages - layout.reference_pages
    layout.blank_pages = sum(1 for p in pages if p.get("type") == "blank")
    layout.appendix_pages = sum(1 for p in pages if p.get("type") == "appendix")
    layout.figure_pages = sum(1 for p in pages if p.get("type") == "figure")
    layout.words = int(report.get("w") or 0)
    layout.characters = sum(int(p.get("c", 0)) for p in pages)
    layout.body_font = report.get("bodyfontsize")
    layout.reference_font = next((p["reffontsize"] for p in pages if "reffontsize" in p), layout.body_font)
    layout.leading = report.get("leading")
    margins = report.get("margin")
    layout.margins = tuple(margins) if margins and any(margins) else None
    layout.columns = report.get("columns") or None
    size = report.get("papersize")
    layout.paper_size = (float(size[0]), float(size[1])) if size and len(size) == 2 else None
    layout.page_number_margin = report.get("nummargin")
    layout.mixed_paper_sizes = any("papersize" in p for p in pages)
    return layout


def evaluate(layout: Layout, rules: FormatRules, first_page_text: str | None) -> list[Finding]:
    """Check a layout against the format rules of a venue."""
    findings = []

    def add(check: str, severity: Severity, message: str) -> None:
        findings.append(Finding(f"layout.{check}", severity, message))

    if layout.paper_size:
        height, width = layout.paper_size
        expected_height, expected_width = rules.paper_size
        if width > height:
            add("paper-size", Severity.ERROR, f"landscape pages ({height:g} x {width:g} pt), possibly slides")
        elif abs(height - expected_height) > rules.paper_size_tolerance or \
                abs(width - expected_width) > rules.paper_size_tolerance:
            add("paper-size", Severity.ERROR,
                f"paper size {height:g} x {width:g} pt, expected {expected_height:g} x {expected_width:g} pt")
    if layout.mixed_paper_sizes:
        add("mixed-paper-sizes", Severity.WARNING, "pages of different sizes")
    if layout.main_pages > rules.main_pages:
        add("main-pages", Severity.ERROR, f"{layout.main_pages} pages of main text, limit {rules.main_pages}")
    if layout.reference_pages > rules.reference_pages:
        add("reference-pages", Severity.ERROR,
            f"{layout.reference_pages} reference-only pages, limit {rules.reference_pages}")
    if layout.references_start is None and layout.main_pages > MIN_PAGES_WITH_REFERENCES:
        add("no-references", Severity.WARNING, "no references section found")
    if layout.body_font and layout.body_font > rules.body_font_max:
        add("body-font", Severity.ERROR, f"body font {layout.body_font:g} pt, limit {rules.body_font_max:g} pt")
    if layout.reference_font and layout.reference_font < rules.reference_font_min:
        add("reference-font", Severity.ERROR,
            f"reference font {layout.reference_font:g} pt, minimum {rules.reference_font_min:g} pt")
    if layout.columns and layout.columns != rules.columns:
        add("columns", Severity.ERROR, f"{layout.columns} column(s), expected {rules.columns}")
    if rules.margins and layout.margins and len(layout.margins) == 4:
        off = [abs(got - want) > rules.margin_tolerance for got, want in zip(layout.margins, rules.margins)]
        if any(off):
            add("margins", Severity.ERROR,
                f"margins {_join(layout.margins)} pt, expected {_join(rules.margins)} "
                f"within {rules.margin_tolerance:g} pt")
    if layout.page_number_margin is not None and rules.page_numbers != "ignore":
        severity = Severity.ERROR if rules.page_numbers == "error" else Severity.WARNING
        add("page-numbers", severity, "page numbers present")
    if layout.total_pages > 2 and layout.words < layout.total_pages * MIN_WORDS_PER_PAGE:
        add("low-word-density", Severity.WARNING,
            f"{layout.words} words on {layout.total_pages} pages, possibly slides or a scan")
    if layout.blank_pages:
        add("blank-pages", Severity.WARNING, f"{layout.blank_pages} blank page(s)")
    if layout.headings:
        for heading in rules.required_headings:
            if not any(heading in name for name in layout.headings):
                add("missing-heading", Severity.WARNING, f"no heading containing {heading!r}")
    elif rules.required_headings:
        add("no-headings", Severity.INFO, "banal found no section headings")
    if rules.require_abstract and first_page_text is not None and not ABSTRACT.search(first_page_text):
        add("missing-abstract", Severity.WARNING, "no abstract on the first page")
    return findings


def inspect(paper: Paper, profile: Profile) -> LayoutResult:
    """Measure the layout of a paper with banal and check it against the profile."""
    try:
        layout = measure(run_banal(paper.pdf))
    except (BanalError, tools.ToolError) as exc:
        return LayoutResult(None, [Finding("layout.error", Severity.WARNING, f"banal could not read the PDF: {exc}")])
    return LayoutResult(layout, evaluate(layout, profile.format, _first_page_text(paper.pdf)))


def check(paper: Paper, profile: Profile, workdir: Path) -> list[Finding]:
    """Return the format findings of a paper."""
    return inspect(paper, profile).findings


def _first_page_text(pdf: Path) -> str | None:
    try:
        with pymupdf.open(pdf) as document:
            return document[0].get_text() if document.page_count else None
    except (RuntimeError, ValueError):
        return None


def _normalize(heading: str) -> str:
    return re.sub(r"\s+", " ", NUMBERING.sub("", heading.strip())).lower()


def _join(values) -> str | None:
    return None if values is None else ", ".join(f"{v:g}" for v in values)

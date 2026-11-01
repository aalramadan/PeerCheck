"""Hidden text and prompt injection in a submission PDF, found with pdfguardrail and PyMuPDF.

pdfguardrail 0.3.0 (MIT, https://github.com/sugannathan/PDFs-Guardrail) does the scan. It renders each page with
and without its text, flags text that leaves no ink, and adds rules for white text, text in the color of its
background, tiny text, the invisible render mode, zero opacity, hidden layers, covered text, off-page text, invisible
Unicode, metadata, annotations, form fields, embedded files, and JavaScript. It then labels each finding as an
injection, hidden data, unknown, or harmless. The check runs it without its optional LLM, since a submission never
leaves the machine.

PeerCheck adds what pdfguardrail misses on the fixtures of tests/fixtures/hidden. First, text cut away by a clipping
path that lies over visible text, found with the TEXT_CLIP flag of PyMuPDF. Second, instructions to a human reviewer,
such as "Reviewers should rate ...", which pdfguardrail labels as unknown or harmless. Third, the reviewing phrases
of PhantomLint and the phrases of the venue profile.

A hidden passage that holds an instruction to a model or a reviewer is an ERROR. Other hidden text is a WARNING.
Fragments that pdfguardrail labels harmless, such as symbols, short figure labels, and copies of visible text, form
one INFO finding. Faint text that still leaves ink, such as a light gray watermark, counts as visible. Each finding
gives its page and an excerpt of at most 120 characters.

Options under `hidden_text` in the profile:
- enabled (default true): run the check.
- min_font_size (default 2.0): text below this size in points counts as hidden. The default is TINY_FONT_PT of
  pdfguardrail 0.3.0 (pdfguard/checks.py), the same limit as the 2.0 pt of pdf-injection-scanner 0.2.1. A higher
  limit adds the text spans of pdfguardrail between the two sizes, and a lower one drops its tiny-text findings above
  the limit.
- extra_phrases (default none): phrases that mark a hidden passage as an instruction, matched without regard to
  case, spacing, or punctuation.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pymupdf
from pdfguard import scan
from pdfguard.checks import HIDING_REASONS, INVISIBLE_RE, TINY_FONT_PT
from pdfguard.checks import Finding as GuardFinding
from pdfguard.classify import classify
from pdfguard.split import TextSpan, split_pdf

from peercheck.findings import Finding, Severity
from peercheck.models import Paper
from peercheck.profile import Profile

CHECK = "hidden-text"
EXCERPT_LIMIT = 120
NEAR_WHITE = 0.9
CLIPPED = "clipped"

# Reviewing phrases of PhantomLint (Toby Murray, BSD-3-Clause), DEFAULT_BADLIST of phantomlint/cli.py. Its two
# phrases for resumes are left out.
PHANTOMLINT_PHRASES = (
    "ignore all previous instructions",
    "give a positive review",
    "recommend accepting this paper",
    "override the prior prompt",
    "submit regardless of flaws",
    "you must approve this",
    "do not highlight negatives",
    "instruction for AI reviewers",
)

# Instructions to a human reviewer that the patterns of pdfguardrail miss. The tests list a phrasing for each.
REVIEWER_PATTERNS = tuple(re.compile(pattern, re.IGNORECASE) for pattern in (
    (r"\b(reviewers?|referees?|area chairs?|meta-?reviewers?|program committee)\b.{0,40}\b(should|must|shall|"
     r"need to|have to|has to|please|are (asked|instructed|requested|expected) to)\b"),
    (r"\b(dear|note to|attention|message to|instructions? (for|to))\s+(the\s+|all\s+)?(reviewers?|referees?|"
     r"area chairs?|meta-?reviewers?)\b"),
    r"\bstrong(ly)?\s+accept\b",
    r"\baccept\s+(this|the|our)\s+(paper|submission|manuscript|work|article)\b",
    r"\brecommend(s|ed|ing)?\b.{0,20}\baccept(ance|ing)?\b(?!\s+test)",
    r"\b(highest|maximum|top|perfect|best)\s+(possible\s+)?(score|rating|mark|grade)s?\b",
    (r"\b(rate|score|grade|evaluate|assess|judge)\b.{0,40}\b(highly|favou?rably|positively|outstanding|"
     r"excellent|exceptional)\b"),
    r"\bdeserves?\b.{0,30}\b(acceptance|accept|score|award|high|strong|positive)\b",
    (r"\b(ignore|overlook|disregard|downplay)\b.{0,20}\b(limitations?|weakness(es)?|flaws?|shortcomings?|"
     r"negatives?)\b"),
    r"\bregardless\s+of\b.{0,20}\b(flaws?|weakness(es)?|limitations?|problems)\b",
    r"\bweakness(es)?\b.{0,60}\b(minor|easily\s+fixable|trivial)\b",
))

SOURCE_RULES = {
    "metadata": "metadata", "xmp": "metadata", "annotation": "annotation", "form_field": "form-field",
    "embedded_file": "embedded-file", "link": "javascript", "javascript": "javascript", "document": "damaged-pdf",
}
# The first reason of a finding in this order names its rule.
REASON_RULES = (
    ("invisible_render_mode", "render-mode"), ("transparent", "transparent"), ("hidden_layer", "hidden-layer"),
    ("off_page", "off-page"), ("covered", "covered"), ("tiny_font", "tiny-text"),
    ("color_matches_background", "background-color"), (CLIPPED, "clipped"), ("no_ink", "no-ink"),
    ("invisible_unicode", "invisible-unicode"),
)
METHODS = {
    "white-text": "white or near-white text",
    "background-color": "text in the color of its background",
    "tiny-text": "text below {size:g} pt",
    "render-mode": "text in the invisible render mode",
    "transparent": "fully transparent text",
    "hidden-layer": "text on a hidden layer",
    "off-page": "text outside the page",
    "covered": "text covered by a filled shape or an image",
    "clipped": "text outside its clipping path",
    "no-ink": "text that leaves no visible ink",
    "invisible-unicode": "invisible Unicode characters",
    "metadata": "document metadata",
    "annotation": "annotation text",
    "form-field": "form field value",
    "embedded-file": "embedded file",
}


def check(paper: Paper, profile: Profile, workdir: Path) -> list[Finding]:
    """Return a finding for each hidden passage of the PDF, an error for each hidden instruction."""
    options = profile.options("hidden_text")
    if not options.get("enabled", True):
        return []
    min_size = float(options.get("min_font_size", TINY_FONT_PT))
    phrases = PHANTOMLINT_PHRASES + _listed(options.get("extra_phrases"))
    try:
        return _scan(Path(paper.pdf), min_size, phrases)
    except Exception as exc:  # noqa: BLE001 - one bad PDF must not stop the run over all submissions
        return [Finding(f"{CHECK}.error", Severity.WARNING, f"The hidden-text scan could not read the PDF ({exc}).")]


def holds_instruction(text: str, phrases: tuple[str, ...] = ()) -> bool:
    """Return True if the text matches a reviewer pattern or contains a phrase, ignoring case and punctuation.

    A phrase also matches text that lost its spaces, as some PDFs store words without them.
    """
    plain = INVISIBLE_RE.sub("", text)
    if any(pattern.search(plain) for pattern in REVIEWER_PATTERNS):
        return True
    words = _words(plain)
    squashed = words.replace(" ", "")
    for phrase in filter(None, map(_words, phrases)):
        if f" {phrase} " in f" {words} " or phrase.replace(" ", "") in squashed:
            return True
    return False


def _scan(pdf: Path, min_size: float, phrases: tuple[str, ...]) -> list[Finding]:
    parts = split_pdf(pdf)
    # use_llm=False keeps pdfguardrail from calling a local model or a web service even when one is configured.
    report = scan(pdf, use_llm=False, parts=parts)
    found = [f for f in report.findings if _kept(f, min_size)]
    tiny = _uncovered(_tiny_text(parts.text_spans, min_size), found)
    clipped = _uncovered(_clipped_text(pdf), found + tiny)
    classify(tiny + clipped, report.clean_text, {}, use_llm=False)
    return _findings(found + tiny + clipped, min_size, phrases)


def _kept(found: GuardFinding, min_size: float) -> bool:
    """Drop text that a reader sees and tiny text above the size limit of the profile."""
    if found.source != "text":
        return True
    hiding = HIDING_REASONS & set(found.reasons)
    if not hiding:
        return "invisible_unicode" in found.reasons
    return not (hiding == {"tiny_font"} and found.details.get("font_size", 0.0) >= min_size)


def _tiny_text(spans: list[TextSpan], min_size: float) -> list[GuardFinding]:
    """Text from the pdfguardrail size limit up to a higher limit of the profile, which pdfguardrail passes over."""
    pieces = [(s.page, s.text.strip(), pymupdf.Rect(s.bbox), s.size) for s in spans
              if TINY_FONT_PT <= s.size < min_size and s.text.strip()]
    return _passages(pieces, "tiny_font")


def _clipped_text(pdf: Path) -> list[GuardFinding]:
    """Characters on the page that a clipping path cuts away, as runs of text per line.

    With TEXT_CLIP, PyMuPDF drops each character that lies wholly outside the clipping path, so the characters that
    only the extraction without the flag returns are the clipped ones. Characters outside the page are left to the
    off-page rule of pdfguardrail.
    """
    pieces = []
    with pymupdf.open(pdf) as doc:
        for number, page in enumerate(doc):
            # Counting the characters first spares the slower comparison on the many pages without clipped text.
            if _char_count(page, pymupdf.TEXTFLAGS_TEXT) == _char_count(page, pymupdf.TEXTFLAGS_TEXT & ~pymupdf.TEXT_CLIP):
                continue
            shown = {_char_key(c) for line in _lines(page, pymupdf.TEXTFLAGS_RAWDICT) for c in line}
            for line in _lines(page, pymupdf.TEXTFLAGS_RAWDICT & ~pymupdf.TEXT_CLIP):
                for chars in _hidden_runs(line, shown, page.rect):
                    text = "".join(c["c"] for c in chars).strip()
                    if text:
                        box = pymupdf.Rect(chars[0]["bbox"])
                        for char in chars[1:]:
                            box |= pymupdf.Rect(char["bbox"])
                        pieces.append((number, text, box, chars[0]["size"]))
    return _passages(pieces, CLIPPED)


def _char_count(page: pymupdf.Page, flags: int) -> int:
    return sum(not c.isspace() for c in page.get_text("text", flags=flags))


def _hidden_runs(line: list[dict], shown: set[tuple], page_rect: pymupdf.Rect) -> list[list[dict]]:
    """Split a line into the runs of characters that the clipped extraction lacks and that lie on the page."""
    runs, run = [], []
    for char in line:
        if _char_key(char) not in shown and page_rect.contains(char["origin"]):
            run.append(char)
        elif run:
            runs.append(run)
            run = []
    return runs + [run] if run else runs


def _lines(page: pymupdf.Page, flags: int) -> list[list[dict]]:
    lines = []
    for block in page.get_text("rawdict", flags=flags)["blocks"]:
        for line in block.get("lines", []):
            lines.append([dict(c, size=span["size"]) for span in line["spans"] for c in span["chars"]])
    return lines


def _char_key(char: dict) -> tuple[float, float, str]:
    return round(char["origin"][0], 1), round(char["origin"][1], 1), char["c"]


def _passages(pieces: list[tuple[int, str, pymupdf.Rect, float]], reason: str) -> list[GuardFinding]:
    """Join runs of text into passages when a run continues the one before it in reading order.

    A run continues the one before when it follows it on the same line or starts the next line, as in a wrapped
    paragraph. Runs in other cells of a table stay apart, as short fragments.
    """
    passages: list[GuardFinding] = []
    previous = None
    for page, text, box, size in pieces:
        if previous is not None and passages[-1].page == page and _continues(previous, box, size):
            passages[-1].text = f"{passages[-1].text} {text}"
            passages[-1].bbox = list(pymupdf.Rect(passages[-1].bbox) | box)
        else:
            passages.append(GuardFinding("text", text, [reason], page, list(box), details={"font_size": size}))
        previous = box
    return passages


def _continues(previous: pymupdf.Rect, box: pymupdf.Rect, size: float) -> bool:
    same_line = abs(box.y0 - previous.y0) <= size / 2 and -size <= box.x0 - previous.x1 <= 3 * size
    next_line = -size / 2 <= box.y0 - previous.y1 <= size and box.x0 <= previous.x1
    return same_line or next_line


def _uncovered(extra: list[GuardFinding], found: list[GuardFinding]) -> list[GuardFinding]:
    """Keep the new passages whose center lies outside every hidden passage that is already found."""
    boxes = [(f.page, pymupdf.Rect(f.bbox) + (-1, -1, 1, 1)) for f in found
             if f.source == "text" and f.bbox and (HIDING_REASONS | {CLIPPED}) & set(f.reasons)]
    kept = []
    for passage in extra:
        box = pymupdf.Rect(passage.bbox)
        center = pymupdf.Point((box.x0 + box.x1) / 2, (box.y0 + box.y1) / 2)
        if not any(page == passage.page and other.contains(center) for page, other in boxes):
            kept.append(passage)
    return kept


def _findings(found: list[GuardFinding], min_size: float, phrases: tuple[str, ...]) -> list[Finding]:
    findings, fragments = [], []
    for item in found:
        rule = _rule(item)
        page = None if item.page is None else item.page + 1
        text = _excerpt(item.decoded or item.text)
        if rule == "damaged-pdf":
            findings.append(Finding(f"{CHECK}.{rule}", Severity.INFO,
                                    "The PDF was damaged and had to be repaired, so the scan may miss content."))
            continue
        if rule == "javascript":
            message = f'Active content (JavaScript) in the PDF: "{text}"'
            findings.append(Finding(f"{CHECK}.{rule}", Severity.WARNING, message, page, text))
            continue
        method = METHODS[rule].format(size=min_size)
        if item.decoded:
            method = f"{method} that encode a message"
        if item.label == "injection" or holds_instruction(item.decoded or item.text, phrases):
            message = f'Hidden instruction to a model or a reviewer ({method}): "{text}"'
            findings.append(Finding(f"{CHECK}.{rule}", Severity.ERROR, message, page, text))
        elif item.label == "harmless":
            fragments.append((page, text))
        else:
            kind = "numbers" if item.label == "data" else "passage"
            message = f'Hidden {kind} ({method}): "{text}"'
            findings.append(Finding(f"{CHECK}.{rule}", Severity.WARNING, message, page, text))
    findings.sort(key=lambda f: f.page or 0)
    if fragments:
        noun = "fragment" if len(fragments) == 1 else "fragments"
        message = (f"{len(fragments)} hidden {noun} without an instruction, such as symbols, figure labels, "
                   "or copies of visible text")
        evidence = _excerpt(" | ".join(text for _, text in fragments))
        findings.append(Finding(f"{CHECK}.fragments", Severity.INFO, message, fragments[0][0], evidence))
    return findings


def _rule(found: GuardFinding) -> str:
    if found.source in SOURCE_RULES:
        return SOURCE_RULES[found.source]
    if found.decoded:
        return "invisible-unicode"
    rule = next((rule for reason, rule in REASON_RULES if reason in found.reasons), "no-ink")
    color = found.details.get("color") or [0.0]
    if rule in ("background-color", "no-ink") and min(color) >= NEAR_WHITE:
        return "white-text"
    return rule


def _excerpt(text: str) -> str:
    text = " ".join(INVISIBLE_RE.sub("", text).split())
    return text if len(text) <= EXCERPT_LIMIT else text[: EXCERPT_LIMIT - 3].rstrip() + "..."


def _words(text: str) -> str:
    return " ".join(re.sub(r"[^0-9a-z]+", " ", text.lower()).split())


def _listed(value: Any) -> tuple[str, ...]:
    if not value:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(str(item) for item in value)

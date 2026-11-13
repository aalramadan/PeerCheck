"""Active content in a submission PDF, such as scripts and actions that open web addresses by themselves, sorted into
the nine categories of mubanal, the PDF analyzer whose report HotCRP reads, with a pikepdf scan of every object."""

from __future__ import annotations

import re
import zlib
from dataclasses import dataclass
from pathlib import Path

import pikepdf

from peercheck.findings import Finding, Severity, excerpt
from peercheck.models import Paper
from peercheck.profile import Profile, ProfileError

CHECK = "active-content"
OPTIONS = "active_content"
# The categories of UnsafeScanner in src/extract.cc of mubanal (AGPL-3.0), in the order of its README.
DANGEROUS = {
    "javascript": "JavaScript that a PDF viewer may run when a reviewer opens the paper or clicks in it",
    "launch": "Launch action that can start a program on the computer of the reviewer",
    "submitform": "Form action that sends data to a web address (SubmitForm or ImportData)",
    "autoaction": "Action that opens a web address or another file by itself when the PDF opens or a page shows",
    "richmedia": "RichMedia annotation, which embeds Flash or ActionScript",
    "xfa": "XFA form, which may run scripts and open web connections",
    "externalref": ("Content that the PDF loads from outside the file (a URL file specification, an external "
                    "stream, or a reference XObject)"),
}
ADVISORY = {
    "rellaunch": "Link that opens a file by a relative path, such as an artifact file",
    "multimedia": "Movie or sound clip played from a file outside the PDF",
}
TRIGGERED = frozenset({"/URI", "/GoToR", "/GoToE", "/Launch"})
COMMAND_FORMS = ("/Win", "/Mac", "/Unix")
EXECUTABLE_SUFFIXES = (".exe", ".bat", ".cmd", ".com", ".scr", ".pif", ".msi", ".ps1", ".vbs", ".js", ".jar",
                       ".app", ".sh", ".command")
# hyperref writes \href{run:./proof.v:164} as the file ./proof.v:164, with the line after a colon.
LINE_SUFFIX = re.compile(r":\d*$")
# Nesting and chains of next actions stop at this depth, as in mubanal, and a PDF may nest objects without end.
MAX_DEPTH = 64
# A small script stream may inflate to gigabytes, therefore decoding stops at this size.
SCRIPT_LIMIT = 1 << 16
# The target of each indirect action that the walk of a trigger reached, None for a chain without such a target.
Targets = dict[tuple[int, int], str | None]


@dataclass(frozen=True)
class Hit:
    """One object of the PDF in one category, with the object number and a short excerpt of what it does."""

    category: str
    number: int
    evidence: str = ""


def check(paper: Paper, profile: Profile, workdir: Path) -> list[Finding]:
    """Return one finding for each category of active content in the PDF, with its pages and an example.

    The seven dangerous categories give a finding of the severity of the profile, while relative launches and
    external clips, which mubanal calls advisory, give an INFO note. Clickable web links stay unflagged, as in
    mubanal, except a javascript: link, which pdfguardrail reports as JavaScript.

    Options under `active_content` in the profile: severity (default warning): the severity of the dangerous
    categories, error for a venue whose call forbids scripts or other active content.
    """
    severity = _severity(profile.options(OPTIONS).get("severity", Severity.WARNING.value))
    try:
        with pikepdf.open(paper.pdf) as pdf:
            hits = _scan(pdf)
            pages = _object_pages(pdf) if hits else {}
    except Exception as exc:  # noqa: BLE001 - one PDF that qpdf cannot read must not stop the run over all papers
        return [Finding(f"{CHECK}.error", Severity.WARNING,
                        f"The active-content scan could not read the PDF ({type(exc).__name__}).")]
    return _findings(hits, pages, severity)


def _severity(value: object) -> Severity:
    try:
        return Severity(str(value).lower())
    except ValueError:
        raise ProfileError(f"{OPTIONS}.severity must be info, warning, or error, not {value!r}") from None


def _scan(pdf: pikepdf.Pdf) -> list[Hit]:
    """Sweep every object of the PDF, also those that nothing references, and return what each one holds."""
    hits: list[Hit] = []
    targets: Targets = {}
    for obj in pdf.objects:
        # pikepdf gives numbers and other plain values as Python objects, which hold no action.
        if not _is_container(obj):
            continue
        number = obj.objgen[0]
        # In a stream dictionary /F names a file that holds the data of the stream. A tool for content credentials
        # (C2PA) writes an /F that names no file, which loads nothing.
        if isinstance(obj, pikepdf.Stream) and (external := _file_name(obj.get("/F"))):
            hits.append(Hit("externalref", number, external))
        _visit(obj, number, hits, targets, 0)
    return hits


def _visit(obj: object, number: int, hits: list[Hit], targets: Targets, depth: int) -> None:
    """Check a dictionary and its direct children, since each indirect child is an object of the sweep."""
    if depth >= MAX_DEPTH:
        return
    if isinstance(obj, (pikepdf.Dictionary, pikepdf.Stream)):
        _check_dictionary(obj, number, hits, targets)
        children = obj.values()
    elif isinstance(obj, pikepdf.Array):
        children = obj
    else:
        return
    for child in children:
        if _is_container(child) and not child.is_indirect:
            _visit(child, number, hits, targets, depth + 1)


def _check_dictionary(d: pikepdf.Dictionary | pikepdf.Stream, number: int, hits: list[Hit], targets: Targets) -> None:
    kind = _name(d.get("/S"))
    if kind == "/JavaScript":
        hits.append(Hit("javascript", number, _script(d.get("/JS"))))
    elif kind == "/Launch":
        hits.append(Hit(_launch_category(d), number, _launch_target(d)))
    elif kind in ("/SubmitForm", "/ImportData"):
        hits.append(Hit("submitform", number, _file_name(d.get("/F"))))
    elif kind == "/RichMediaExecute":
        hits.append(Hit("richmedia", number))
    elif kind == "/MCD" and _external_file(d.get("/D")):
        hits.append(Hit("multimedia", number, _file_name(d.get("/D"))))
    elif kind == "/URI" and _text(d.get("/URI")).strip().lower().startswith("javascript:"):
        hits.append(Hit("javascript", number, _text(d.get("/URI"))))
    elif "/JS" in d:
        # A script outside a JavaScript action, such as the /JS of a Rendition action.
        hits.append(Hit("javascript", number, _script(d.get("/JS"))))
    subtype = _name(d.get("/Subtype"))
    if subtype == "/RichMedia":
        hits.append(Hit("richmedia", number))
    elif subtype == "/Movie":
        movie = d.get("/Movie")
        if isinstance(movie, pikepdf.Dictionary) and _external_file(movie.get("/F")):
            hits.append(Hit("multimedia", number, _file_name(movie.get("/F"))))
    elif subtype == "/Form" and "/Ref" in d:
        # A reference XObject draws a page of another PDF file.
        hits.append(Hit("externalref", number, _file_name(_entry(d.get("/Ref"), "/F"))))
    if _name(d.get("/FS")) == "/URL":
        hits.append(Hit("externalref", number, _text(d.get("/F"))))
    if "/XFA" in d:
        hits.append(Hit("xfa", number))
    events = d.get("/AA")
    for trigger in [d.get("/OpenAction"), *(events.values() if isinstance(events, pikepdf.Dictionary) else ())]:
        target = _trigger_target(trigger, targets, 0)
        if target is not None:
            hits.append(Hit("autoaction", number, target))


def _trigger_target(action: object, targets: Targets, depth: int) -> str | None:
    """Return the target of the first action in a chain of next actions that opens a web address or a file without a
    click, or None if the chain holds none.

    A script in such a chain is flagged where the sweep finds it, and a destination array or a GoTo action that stays
    inside the PDF is no finding. The result of each indirect action is kept, which ends cycles of next actions and
    spares a second walk of a chain that several triggers share.
    """
    if depth >= MAX_DEPTH or not isinstance(action, pikepdf.Dictionary):
        return None
    key = action.objgen if action.is_indirect else None
    if key is not None:
        if key in targets:
            return targets[key]
        targets[key] = None
    if _name(action.get("/S")) in TRIGGERED:
        found = _text(action.get("/URI")) or _launch_target(action)
    else:
        following = action.get("/Next")
        successors = following if isinstance(following, pikepdf.Array) else [following]
        found = next((target for successor in successors
                      if (target := _trigger_target(successor, targets, depth + 1)) is not None), None)
    if key is not None:
        targets[key] = found
    return found


def _launch_category(d: pikepdf.Dictionary | pikepdf.Stream) -> str:
    """Return rellaunch for a launch of a bare relative path, such as an artifact file, and launch otherwise.

    A command form for Windows, macOS, or Unix, a missing target, an absolute path or a web address, and an
    executable file can start a program.
    """
    if any(form in d for form in COMMAND_FORMS):
        return "launch"
    target = d.get("/F")
    if isinstance(target, pikepdf.Dictionary):
        unicode_name = target.get("/UF")
        target = unicode_name if isinstance(unicode_name, pikepdf.String) else target.get("/F")
    if not isinstance(target, pikepdf.String):
        return "launch"
    path = LINE_SUFFIX.sub("", str(target).strip().lower())
    absolute = path.startswith(("/", "\\")) or "://" in path or (len(path) > 2 and path[1] == ":" and path[2] in "/\\")
    if not path or absolute or path.endswith(EXECUTABLE_SUFFIXES):
        return "launch"
    return "rellaunch"


def _launch_target(d: pikepdf.Dictionary | pikepdf.Stream) -> str:
    """Return the file of a launch or a remote action, with the command and parameters of a Windows launch."""
    parts = [_file_name(d.get("/F"))]
    command = d.get("/Win")
    if isinstance(command, pikepdf.Dictionary):
        parts += [_text(command.get("/F")), _text(command.get("/P"))]
    return " ".join(part for part in parts if part)


def _external_file(spec: object) -> bool:
    """Return True if a media file specification names data outside the PDF.

    A dictionary with /EF embeds the data, a stream stands for embedded data, and a string is always a path.
    """
    if isinstance(spec, pikepdf.Stream):
        return False
    if isinstance(spec, pikepdf.Dictionary):
        return "/EF" not in spec
    return isinstance(spec, pikepdf.String)


def _file_name(spec: object) -> str:
    """Return the name in a file specification, given as a string or as a dictionary with its name variants."""
    if isinstance(spec, pikepdf.String):
        return str(spec)
    if isinstance(spec, pikepdf.Dictionary):
        return next((str(name) for key in ("/UF", "/F", "/Unix", "/DOS", "/Mac")
                     if isinstance(name := spec.get(key), pikepdf.String)), "")
    return ""


def _script(js: object) -> str:
    """Return the text of a script, held in a string or in a stream without a filter or in FlateDecode."""
    if isinstance(js, pikepdf.String):
        return str(js)
    if not isinstance(js, pikepdf.Stream):
        return ""
    raw = js.read_raw_bytes()
    filters = js.get("/Filter")
    if isinstance(filters, pikepdf.Array) and len(filters) == 1:
        filters = filters[0]
    if filters is None:
        data = raw[:SCRIPT_LIMIT]
    elif _name(filters) == "/FlateDecode":
        try:
            data = zlib.decompressobj().decompress(raw, SCRIPT_LIMIT)
        except zlib.error:
            return ""
    else:
        return ""
    if data[:2] in (b"\xfe\xff", b"\xff\xfe"):
        return data.decode("utf-16", "replace")
    return data.decode("latin-1")


def _object_pages(pdf: pikepdf.Pdf) -> dict[int, int]:
    """Return the first page that reaches each object, without passing through another page or the page tree.

    A link to another page, the page of an annotation, and the parent of a page lead to other pages, therefore the
    walk stops at every page and at every /Parent. Objects that no page reaches, such as the open action of the
    document, have no page.
    """
    owners: dict[int, int] = {}
    try:
        pages = list(pdf.pages)
    except Exception:  # noqa: BLE001 - a broken page tree leaves every finding without a page
        return owners
    for number, page in enumerate(pages, start=1):
        root = page.obj
        owners.setdefault(root.objgen[0], number)
        stack = [root]
        while stack:
            for child in _children(stack.pop()):
                if child.is_indirect:
                    if child.objgen[0] in owners or _is_page(child):
                        continue
                    owners[child.objgen[0]] = number
                stack.append(child)
    return owners


def _is_page(obj: object) -> bool:
    return isinstance(obj, pikepdf.Dictionary) and _name(obj.get("/Type")) in ("/Page", "/Pages")


def _children(obj: object) -> list:
    if isinstance(obj, (pikepdf.Dictionary, pikepdf.Stream)):
        return [value for key, value in obj.items() if key != "/Parent" and _is_container(value)]
    if isinstance(obj, pikepdf.Array):
        return [value for value in obj if _is_container(value)]
    return []


def _findings(hits: list[Hit], pages: dict[int, int], severity: Severity) -> list[Finding]:
    """Give one finding per category, in the order of the categories, with its pages and the first example."""
    findings = []
    for category, description in {**DANGEROUS, **ADVISORY}.items():
        found = [hit for hit in hits if hit.category == category]
        if not found:
            continue
        where = sorted({pages[hit.number] for hit in found if hit.number in pages})
        message = description + (f", on pages {_join(where)}" if len(where) > 1 else "")
        evidence = excerpt(next((hit.evidence for hit in found if hit.evidence), ""))
        level = severity if category in DANGEROUS else Severity.INFO
        findings.append(Finding(f"{CHECK}.{category}", level, message, where[0] if where else None, evidence))
    return findings


def _is_container(value: object) -> bool:
    return isinstance(value, (pikepdf.Dictionary, pikepdf.Array, pikepdf.Stream))


def _name(value: object) -> str:
    return str(value) if isinstance(value, pikepdf.Name) else ""


def _text(value: object) -> str:
    return str(value) if isinstance(value, pikepdf.String) else ""


def _entry(value: object, key: str) -> object:
    return value.get(key) if isinstance(value, pikepdf.Dictionary) else None


def _join(numbers: list[int]) -> str:
    items = [str(number) for number in numbers]
    if len(items) < 3:
        return " and ".join(items)
    return f"{', '.join(items[:-1])}, and {items[-1]}"

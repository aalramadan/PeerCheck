"""Accessibility of a submission PDF, read with pikepdf: the quick structure test of the tags, the language, the title,
and the alternative text of the figures, after rules 6.2-1, 7.1-11, 7.2-29, 7.1-9, and 7.3-1 of the PDF/UA-1 profile
of veraPDF in external/verapdf/. veraPDF itself runs the full PDF/UA check, which PeerCheck leaves out.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pikepdf

from peercheck.findings import Finding, Severity
from peercheck.models import Paper
from peercheck.profile import Profile, ProfileError

CHECK = "accessibility"
# A language identifier after ISO 32000-1, 14.9.2, as rule 7.2-29 tests the /Lang entry.
LANGUAGE = re.compile(r"^[a-zA-Z]{1,8}(-[a-zA-Z0-9]{1,8})*$")
# tagpdf writes the name of the image file as /Alt when \includegraphics has no alt key.
FILE_NAME = re.compile(r"^[^\s/\\]+\.(?:pdf|png|jpe?g|eps|ps|svg|gif|tiff?|bmp|webp)$", re.IGNORECASE)
# Role maps may chain custom types, and a broken file may map them in a circle.
ROLE_DEPTH = 10
QUOTED_LENGTH = 20


@dataclass(frozen=True)
class Figure:
    """A structure element of the type Figure, with its page and its descriptions."""

    page: int | None
    alt: str
    actual_text: bool

    @property
    def described(self) -> bool:
        """Return True for a replacement text or an alternative text other than the name of the image file."""
        return self.actual_text or (bool(self.alt) and not FILE_NAME.match(self.alt))


def check(paper: Paper, profile: Profile, workdir: Path) -> list[Finding]:
    """Return a note for each part of the structure test that the PDF fails, or an error under the profile option.

    enabled (default false): true for a venue that asks for accessible PDFs, which turns the notes on.
    required (default false): true for a venue that requires accessible PDFs, which turns each note into an error.
    """
    options = profile.options(CHECK)
    required = options.get("required", False)
    if not isinstance(required, bool):
        raise ProfileError(f"{CHECK}.required must be true or false")
    if not (required or options.get("enabled", False)):
        return []
    severity = Severity.ERROR if required else Severity.INFO
    try:
        with pikepdf.open(paper.pdf) as pdf:
            problems = _problems(pdf)
    except (pikepdf.PdfError, pikepdf.PasswordError, OSError, ValueError, RecursionError):
        return [Finding(f"{CHECK}.error", Severity.WARNING, "pikepdf could not read the structure of the PDF")]
    return [Finding(f"{CHECK}.{code}", severity, message, page) for code, message, page in problems]


def _problems(pdf: pikepdf.Pdf) -> list[tuple[str, str, int | None]]:
    """Return the code, the message, and the page of each part of the structure test that fails."""
    root = pdf.Root
    tree = root.get("/StructTreeRoot")
    mark_info = root.get("/MarkInfo")
    missing = []
    if not isinstance(tree, pikepdf.Dictionary):
        missing.append("no structure tree")
    if not (isinstance(mark_info, pikepdf.Dictionary) and mark_info.get("/Marked") is True):
        missing.append("/Marked not true in /MarkInfo")
    problems = [("untagged", f"PDF is not tagged ({', '.join(missing)})", None)] if missing else []
    language = _text(root.get("/Lang"))
    if not language:
        problems.append(("no-language", "no document language (/Lang)", None))
    elif not LANGUAGE.match(language):
        problems.append(("no-language", f"document language {language[:QUOTED_LENGTH]!r} is not a language tag",
                         None))
    if not _title(pdf):
        problems.append(("no-title", "no document title (/Title or dc:title)", None))
    figures = _figures(pdf, tree) if isinstance(tree, pikepdf.Dictionary) else []
    undescribed = [figure for figure in figures if not figure.described]
    if undescribed:
        message = f"{len(undescribed)} of {len(figures)} figures without alternative text (/Alt or /ActualText)"
        named = sum(1 for figure in undescribed if figure.alt)
        if named:
            message += f", {named} of them with only the name of the image file"
        page = next((figure.page for figure in undescribed if figure.page), None)
        problems.append(("figure-alt", message, page))
    return problems


def _title(pdf: pikepdf.Pdf) -> bool:
    """Return True if the document information or the XMP metadata holds a title."""
    info = pdf.trailer.get("/Info")
    if isinstance(info, pikepdf.Dictionary) and _text(info.get("/Title")):
        return True
    if "/Metadata" not in pdf.Root:
        return False
    return bool(_text(pdf.open_metadata(set_pikepdf_as_editor=False, update_docinfo=False).get("dc:title")))


def _figures(pdf: pikepdf.Pdf, tree: pikepdf.Dictionary) -> list[Figure]:
    """Return every structure element whose type, through the role maps, is Figure."""
    pages = {page.obj.objgen: number for number, page in enumerate(pdf.pages, start=1)}
    role_map = tree.get("/RoleMap")
    figures = []
    seen = set()
    stack = [(tree.get("/K"), None)]
    while stack:
        item, page = stack.pop()
        if isinstance(item, (pikepdf.Array, pikepdf.Dictionary)) and item.is_indirect:
            if item.objgen in seen:
                continue
            seen.add(item.objgen)
        if isinstance(item, pikepdf.Array):
            stack.extend((kid, page) for kid in reversed(list(item)))
            continue
        if not isinstance(item, pikepdf.Dictionary) or "/S" not in item:
            continue
        page = _page(item, pages) or page
        if _role(item, role_map) == "/Figure":
            figures.append(Figure(page or _kid_page(item, pages), _text(item.get("/Alt")), "/ActualText" in item))
        stack.append((item.get("/K"), page))
    return figures


def _role(element: pikepdf.Dictionary, role_map) -> str:
    """Return the standard type of a structure element through the role map and the role maps of its namespaces."""
    name, namespace = str(element.get("/S")), element.get("/NS")
    for _ in range(ROLE_DEPTH):
        if name == "/Figure":
            break
        target = None
        namespace_map = namespace.get("/RoleMapNS") if isinstance(namespace, pikepdf.Dictionary) else None
        if isinstance(namespace_map, pikepdf.Dictionary) and name in namespace_map:
            target = namespace_map[name]
            if isinstance(target, pikepdf.Array) and len(target) == 2:
                target, namespace = target[0], target[1]
        elif isinstance(role_map, pikepdf.Dictionary) and name in role_map:
            target = role_map[name]
        if not isinstance(target, pikepdf.Name):
            break
        name = str(target)
    return name


def _page(element: pikepdf.Dictionary, pages: dict) -> int | None:
    """Return the number of the page that the /Pg entry of a dictionary names."""
    target = element.get("/Pg")
    return pages.get(target.objgen) if isinstance(target, pikepdf.Dictionary) else None


def _kid_page(element: pikepdf.Dictionary, pages: dict) -> int | None:
    """Return the page of the first marked-content reference among the kids of an element."""
    kids = element.get("/K")
    for kid in kids if isinstance(kids, pikepdf.Array) else [kids]:
        if isinstance(kid, pikepdf.Dictionary) and (page := _page(kid, pages)):
            return page
    return None


def _text(value) -> str:
    """Return a PDF string or a metadata value as stripped text, empty for anything else."""
    return str(value).strip() if isinstance(value, (pikepdf.String, str)) else ""

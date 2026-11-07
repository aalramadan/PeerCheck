"""Author identity hidden in the objects of a submission PDF: figure paths and metadata, the XMP of images, comment
authors, link targets, embedded file names, and earlier revisions. The page text, the document metadata, and each
author match that the SIGSOFT checker reports in the same value are left to that checker."""

from __future__ import annotations

import html
import re
import unicodedata
import zlib
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from peercheck.findings import Finding, Severity
from peercheck.models import Paper, Person
from peercheck.profile import Profile

CHECK = "identity"
EXCERPT_LIMIT = 120
# A small stream may inflate to gigabytes, therefore decoding stops at this size.
STREAM_LIMIT = 1 << 20
# Each earlier revision costs a text extraction, and a PDF may hold thousands of incremental saves.
MAX_REVISIONS = 20

FIGURE_FILE = "the file path of an included figure (PTEX.FileName)"
FIGURE_INFO = "the metadata of an included figure (PTEX.InfoDict {key})"
OBJECT_XMP = "the XMP metadata of {owner}"
IMAGE_XMP = "the XMP metadata inside a JPEG image"
COMMENT_AUTHOR = "the author field of a PDF comment"
LINK_TARGET = "the target of a link"
FILE_NAME = "the name of an embedded file"
FILE_DESCRIPTION = "the description of an embedded file"
OWNERS = {"/Image": "an image", "/Form": "an included figure", "/Page": "a page", "/Annot": "an annotation",
          "/FontDescriptor": "a font", "/EmbeddedFile": "an embedded file"}
# The annotations that PDFBox reads as markup, whose author field (/T) the SIGSOFT checker matches.
MARKUP = frozenset({"/Text", "/FreeText", "/Line", "/Square", "/Circle", "/Polygon", "/PolyLine", "/Highlight",
                    "/Underline", "/Squiggly", "/StrikeOut", "/Stamp", "/Caret", "/Ink", "/FileAttachment", "/Sound"})
SEVERITIES = {"author": Severity.ERROR, "home-folder": Severity.WARNING, "comment-author": Severity.WARNING}
MESSAGES = {"author": "Name or email of an author of this paper in {place}",
            "home-folder": "Home folder of a user account in {place}", "comment-author": "Name in {place}"}

HOME_FOLDER = re.compile(
    r"(?<![\w.~-])(?:(?:/mnt/[a-z]|/cygdrive/[a-z])?/(?:users|home|homes)/"
    r"|[a-z]:[\\/]+(?:users|documents and settings)[\\/]+)(?P<user>[^\\/:*?\"<>|\r\n]+)", re.IGNORECASE)
# Folders of the system and accounts of build services, which name no person.
SHARED_FOLDERS = frozenset({"shared", "public", "default", "default user", "all users", "guest", "user", "runner"})
# The placeholder words of the SIGSOFT checker, PLACEHOLDER in PdfChecker.java.
PLACEHOLDER = re.compile(r"anon|anonymous|anonymi[sz]ed|doe|blind|blinded|nn|nobody|none|email|firstname|lastname|xyz"
                         r"|x{3,}|authors?|example|domain|address|review")
PATH_SEPARATORS = re.compile(r"[._/\\-]")
# The name and email forms of IdentityScanner.java, on text in lower case without accents.
WORD_BEFORE, WORD_AFTER = r"(?<![^\W_])", r"(?![^\W_])"
MIDDLE_INITIAL = r"(?:\s[^\W\d_]\.)?"
MORE_INITIALS = r"(?:\s?-?\s?[^\W\d_]\.)*"
EMAIL_BEFORE, EMAIL_AFTER = r"(?<![\w.%+-])", r"(?![\w-]|\.\w)"
LATEX_ACCENT = re.compile(r"\\[`'^\"~=.uvHtcdbkr]\s*\{?\s*([^\W\d_])\s*\}?")
SPECIAL_LETTERS = {"ø": "o", "ł": "l", "æ": "ae", "œ": "oe", "ß": "ss", "đ": "d", "ð": "d", "þ": "th", "ı": "i"}
XMP_PACKET = re.compile(rb"<x:x[ma]pmeta\b.*?</x:x[ma]pmeta>", re.DOTALL)
XML_TEXT = re.compile(r">([^<>]+)<")
XML_ATTRIBUTE = re.compile(r"""([\w.:-]+)\s*=\s*(?:"([^"]*)"|'([^']*)')""")
XMP_SYNTAX = frozenset({"rdf:about", "rdf:parseType", "x:xmptk"})
DICT_NAME = re.compile(r"/([^\s/<>\[\]()%{}]+)")
# An %%EOF without startxref, such as one inside a stream, ends no revision.
REVISION_END = re.compile(rb"startxref\s+\d+\s+%%EOF")


@dataclass(frozen=True)
class Value:
    """A text of the PDF with its place, its page, and whether the SIGSOFT checker matches the authors in it."""

    place: str
    text: str
    page: int | None = None
    read_by_sigsoft: bool = False


def check(paper: Paper, profile: Profile, workdir: Path) -> list[Finding]:
    """Return a finding for each author name, home-folder path, comment author, or earlier revision in the PDF."""
    patterns = _author_patterns(paper.authors)
    try:
        with pymupdf.open(paper.pdf, filetype="pdf") as document:
            found = sorted(_value_findings(_values(document), patterns), key=lambda f: f.page or 0)
            return found + _revision_findings(document, Path(paper.pdf), patterns)
    except Exception as exc:  # noqa: BLE001 - one PDF that MuPDF cannot read must not stop the run over all papers
        return [Finding(f"{CHECK}.error", Severity.WARNING,
                        f"The identity scan could not read the PDF ({type(exc).__name__}).")]


def _author_patterns(authors: tuple[Person, ...]) -> list[tuple[int, re.Pattern[str]]]:
    """Return the patterns of the name and the email of each author, with the number of the author."""
    patterns = []
    for number, person in enumerate(authors):
        for regex in (_name_regex(person.first, person.last), _email_regex(person.email)):
            if regex:
                patterns.append((number, re.compile(regex)))
    return patterns


def _name_regex(first: str, last: str) -> str:
    """Return a regex of the name in the forms First Last, Last, First, F. Last, and Last, F."""
    given, family = _fold_name(first), _fold_name(last)
    if not (given and family):
        return WORD_BEFORE + _words(given or family) + WORD_AFTER if given or family else ""
    family_words = _words(family)
    forms = []
    for given_words in dict.fromkeys((_words(given), _words(given.split()[0]))):
        forms += [given_words + MIDDLE_INITIAL + r"\s" + family_words, family_words + r"\s?,\s?" + given_words]
    if given[0].isalpha():
        initial = re.escape(given[0])
        forms += [initial + r"\." + MORE_INITIALS + r"\s?" + family_words, family_words + r"\s?,\s?" + initial + r"\."]
    return WORD_BEFORE + "(?:" + "|".join(forms) + ")" + WORD_AFTER


def _email_regex(email: str) -> str:
    folded = _fold(email)[0].strip()
    local, at, domain = folded.partition("@")
    if not (local and at and domain) or " " in folded:
        return ""
    return EMAIL_BEFORE + re.escape(local) + r"\s?@\s?" + re.escape(domain) + EMAIL_AFTER


def _fold_name(name: str) -> str:
    """Fold a name of the author list, where LaTeX accents such as K{\\"a}stner stand for their letters."""
    return _fold(LATEX_ACCENT.sub(r"\1", name).replace("{", "").replace("}", ""))[0].strip()


def _words(folded: str) -> str:
    return r"\s".join(map(re.escape, folded.split()))


def _fold(text: str) -> tuple[str, list[int]]:
    """Return the text in lower case without accents and with single spaces, and the place of each character."""
    chars: list[str] = []
    places: list[int] = []
    for place, char in enumerate(text):
        if char.isspace():
            if chars and chars[-1] == " ":
                continue
            folded = " "
        elif unicodedata.category(char) == "Sk":
            # Old TeX fonts set an accent as a character of its own, as in Ka¨stner.
            continue
        else:
            lower = char.lower()
            folded = SPECIAL_LETTERS.get(lower) or "".join(
                c for c in unicodedata.normalize("NFKD", lower) if not unicodedata.combining(c))
        chars.extend(folded)
        places.extend([place] * len(folded))
    return "".join(chars), places


def _matches(text: str, patterns: list[tuple[int, re.Pattern[str]]], separators: bool) -> list[tuple[int, int, int]]:
    """Return the number of the author and the span of each match, also with path separators read as spaces."""
    readings = (text, PATH_SEPARATORS.sub(" ", text)) if separators else (text,)
    found = []
    for reading in readings:
        folded, places = _fold(reading)
        for number, pattern in patterns:
            found += [(number, places[m.start()], places[m.end() - 1] + 1) for m in pattern.finditer(folded)]
    return found


def _values(document: pymupdf.Document) -> list[Value]:
    """Return the texts of the figures, images, comments, links, and embedded files of the PDF with their places."""
    pages, figures = _first_pages(document)
    catalog = document.pdf_catalog()
    values = []
    for xref in range(1, document.xref_length()):
        keys = document.xref_get_keys(xref)
        page, read = pages.get(xref), xref in figures
        if "PTEX.FileName" in keys:
            values.append(Value(FIGURE_FILE, _string(document, xref, "PTEX.FileName"), page, read))
        if "PTEX.InfoDict" in keys:
            values += [Value(FIGURE_INFO.format(key=key), text, page, read)
                       for key, text in _entries(document, xref, "PTEX.InfoDict")]
        metadata = _reference(document, xref, "Metadata") if "Metadata" in keys and xref != catalog else 0
        if metadata:
            place = OBJECT_XMP.format(owner=_owner(document, xref))
            values += [Value(place, text, page, read) for text in _xmp_texts(_stream(document, metadata))]
        if "Filter" in keys and document.xref_get_key(xref, "Filter")[1].strip("[] ") in ("/DCTDecode", "/JPXDecode"):
            for packet in XMP_PACKET.findall(document.xref_stream_raw(xref) or b""):
                values += [Value(IMAGE_XMP, text, page) for text in _xmp_texts(packet)]
    for number, page in enumerate(document, start=1):
        for xref, _, _ in page.annot_xrefs():
            if xref > 0:
                values += _annotation_values(document, xref, number)
    for name in document.embfile_names():
        info = document.embfile_info(name)
        values += [Value(FILE_NAME, text) for text in dict.fromkeys((name, info["filename"], info["ufilename"]))]
        values.append(Value(FILE_DESCRIPTION, info["description"]))
    return [value for value in values if value.text.strip()]


def _first_pages(document: pymupdf.Document) -> tuple[dict[int, int], set[int]]:
    """Return the first page of each page, figure, image, and annotation, and the figures that the pages reach."""
    pages: dict[int, int] = {}
    figures: set[int] = set()
    for number, page in enumerate(document, start=1):
        forms = [item[0] for item in document.get_page_xobjects(number - 1)]
        figures.update(forms)
        images = [item[0] for item in document.get_page_images(number - 1, full=True)]
        annotations = [item[0] for item in page.annot_xrefs()]
        for xref in [page.xref, *forms, *images, *annotations]:
            pages.setdefault(xref, number)
    return pages, figures


def _annotation_values(document: pymupdf.Document, xref: int, page: int) -> list[Value]:
    """Return the author of a comment, the target of a link, and the name of a file attached to a comment."""
    subtype = document.xref_get_key(xref, "Subtype")[1]
    values = []
    if subtype in MARKUP:
        values.append(Value(COMMENT_AUTHOR, _string(document, xref, "T"), page, True))
    if subtype == "/Link":
        values.append(Value(LINK_TARGET, _string(document, xref, "A/URI"), page, True))
        values += [Value(LINK_TARGET, name, page) for name in _file_names(document, xref, "A/F")]
    if subtype == "/FileAttachment":
        values += [Value(FILE_NAME, name, page) for name in _file_names(document, xref, "FS")]
        values.append(Value(FILE_DESCRIPTION, _string(document, xref, "FS/Desc"), page))
    return values


def _string(document: pymupdf.Document, xref: int, key: str) -> str:
    kind, value = document.xref_get_key(xref, key)
    return value if kind == "string" else ""


def _reference(document: pymupdf.Document, xref: int, key: str) -> int:
    kind, value = document.xref_get_key(xref, key)
    return int(value.split()[0]) if kind == "xref" else 0


def _entries(document: pymupdf.Document, xref: int, key: str) -> list[tuple[str, str]]:
    """Return the string entries of the dictionary at the key, held in the object or referenced from it."""
    kind, value = document.xref_get_key(xref, key)
    if kind == "xref":
        names = document.xref_get_keys(int(value.split()[0]))
    elif kind == "dict":
        names = DICT_NAME.findall(value)
    else:
        return []
    return [(name, text) for name in dict.fromkeys(names) if (text := _string(document, xref, f"{key}/{name}"))]


def _file_names(document: pymupdf.Document, xref: int, key: str) -> list[str]:
    """Return the file name at the key, given as a string or as a file specification with its name variants."""
    kind, value = document.xref_get_key(xref, key)
    if kind == "string":
        return [value]
    return list(dict.fromkeys(_string(document, xref, f"{key}/{name}") for name in ("UF", "F", "DOS", "Mac", "Unix")))


def _owner(document: pymupdf.Document, xref: int) -> str:
    """Name the kind of object that holds an XMP packet, such as an image."""
    for key in ("Subtype", "Type"):
        name = document.xref_get_key(xref, key)[1]
        if name in OWNERS:
            return OWNERS[name]
    return "a PDF object"


def _stream(document: pymupdf.Document, xref: int) -> bytes:
    """Return the data of a stream without a filter or in FlateDecode, at most STREAM_LIMIT bytes of it."""
    raw = document.xref_stream_raw(xref) or b""
    kind, value = document.xref_get_key(xref, "Filter")
    if kind == "null":
        return raw[:STREAM_LIMIT]
    if value.strip("[] ") != "/FlateDecode":
        return b""
    try:
        return zlib.decompressobj().decompress(raw, STREAM_LIMIT)
    except zlib.error:
        return b""


def _xmp_texts(data: bytes) -> list[str]:
    """Return the text values and the attribute values of an XMP packet, without its syntax attributes."""
    text = data.decode("utf-16" if data[:2] in (b"\xfe\xff", b"\xff\xfe") else "utf-8", "replace")
    values = XML_TEXT.findall(text)
    values += [double or single for name, double, single in XML_ATTRIBUTE.findall(text)
               if name not in XMP_SYNTAX and not name.startswith("xmlns")]
    return [html.unescape(value).strip() for value in values]


def _value_findings(values: list[Value], patterns: list[tuple[int, re.Pattern[str]]]) -> list[Finding]:
    """Give one finding for each kind of hit, place, and author, home folder, or comment author."""
    groups: dict[tuple[str, str, object], list[tuple[int | None, str]]] = {}
    for value in values:
        hit = _hit(value, patterns)
        if hit:
            code, key, evidence = hit
            groups.setdefault((code, value.place, key), []).append((value.page, evidence))
    findings = []
    for (code, place, _), hits in groups.items():
        pages = [page for page, _ in hits if page]
        evidence = _excerpt(" | ".join(dict.fromkeys(text for _, text in hits)))
        findings.append(Finding(f"{CHECK}.{code}", SEVERITIES[code], MESSAGES[code].format(place=place),
                                min(pages, default=None), evidence))
    return findings


def _hit(value: Value, patterns: list[tuple[int, re.Pattern[str]]]) -> tuple[str, object, str] | None:
    """Return the code, the group key, and the evidence of what a value reveals, or None if it reveals nothing new."""
    if value.read_by_sigsoft:
        # The SIGSOFT checker reports an author match in this value, and it reads only a figure path with separators.
        if _matches(value.text, patterns, value.place == FIGURE_FILE):
            return None
    else:
        match = next(iter(_matches(value.text, patterns, True)), None)
        if match:
            number, start, end = match
            return "author", number, _around(value.text, start, end)
    home = _home_folder(value.text)
    if home:
        return "home-folder", home["user"].strip().casefold(), _around(value.text, home.start(), home.end())
    if value.place == COMMENT_AUTHOR and _is_name(value.text):
        return "comment-author", _fold(value.text)[0].strip(), " ".join(value.text.split())
    return None


def _home_folder(text: str) -> re.Match[str] | None:
    """Return the first home-folder path in the text whose folder names a person."""
    return next((m for m in HOME_FOLDER.finditer(text) if m["user"].strip().casefold() not in SHARED_FOLDERS), None)


def _is_name(text: str) -> bool:
    """Return True if the text holds a letter and none of the placeholder words of the SIGSOFT checker."""
    words = [re.sub(r"\d+$", "", word) for word in re.split(r"[\W_]+", text.lower())]
    return any(c.isalpha() for c in text) and not any(word and PLACEHOLDER.fullmatch(word) for word in words)


def _revision_findings(document: pymupdf.Document, pdf: Path,
                       patterns: list[tuple[int, re.Pattern[str]]]) -> list[Finding]:
    """Return an error for each author that an earlier revision names and the final one does not, else a note."""
    count = document.version_count
    if count < 2:
        return []
    found, searched = [], 0
    if patterns:
        named = {number for _, text in _texts(document) for number, _, _ in _matches(text, patterns, False)}
        data = pdf.read_bytes()
        for end in [match.end() for match in REVISION_END.finditer(data)][:-1][:MAX_REVISIONS]:
            texts = _revision_texts(data[:end])
            searched += texts is not None
            for page, text in texts or []:
                for number, start, stop in _matches(text, patterns, False):
                    if number not in named:
                        named.add(number)
                        where = "the page text" if page else "the document metadata"
                        message = (f"Name or email of an author of this paper in {where} of an earlier revision that "
                                   "an incremental save keeps")
                        found.append(Finding(f"{CHECK}.earlier-revision", Severity.ERROR, message, page,
                                             _around(text, start, stop)))
    if found:
        return found
    message = f"The PDF keeps {count} saved revisions from incremental saves, which leave the earlier ones readable"
    if searched:
        message += "; no earlier revision names an author of this paper"
    return [Finding(f"{CHECK}.revisions", Severity.INFO, message, evidence=f"{count} revisions")]


def _revision_texts(data: bytes) -> list[tuple[int | None, str]] | None:
    """Return the texts of the revision that the bytes end with, or None if they end with no whole revision."""
    try:
        with pymupdf.open(stream=data, filetype="pdf") as revision:
            return None if revision.is_repaired else _texts(revision)
    except (RuntimeError, pymupdf.mupdf.FzErrorBase):
        return None


def _texts(document: pymupdf.Document) -> list[tuple[int | None, str]]:
    """Return the text of each page with its number and the values of the document information and XMP."""
    texts: list[tuple[int | None, str]] = [(number, page.get_text()) for number, page in enumerate(document, start=1)]
    texts += [(None, value) for value in document.metadata.values() if value]
    metadata = _reference(document, document.pdf_catalog(), "Metadata")
    if metadata:
        texts += [(None, text) for text in _xmp_texts(_stream(document, metadata))]
    return texts


def _around(text: str, start: int, end: int) -> str:
    """Return the text around a span, cut to EXCERPT_LIMIT characters with an ellipsis at each cut."""
    if len(text) > EXCERPT_LIMIT:
        begin = max(0, min(start - (EXCERPT_LIMIT - (end - start)) // 2, len(text) - EXCERPT_LIMIT))
        cut = text[begin:begin + EXCERPT_LIMIT]
        text = ("..." if begin else "") + cut + ("..." if begin + EXCERPT_LIMIT < len(text) else "")
    return " ".join(text.split())


def _excerpt(text: str) -> str:
    return text if len(text) <= EXCERPT_LIMIT else text[: EXCERPT_LIMIT - 3].rstrip() + "..."

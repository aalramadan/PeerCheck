"""Images and file size of a submission PDF, read with PyMuPDF: a file above the size limit of the venue, images above
the 34 megapixels at which arXiv warns, and pictures placed at a resolution too low to read."""

from __future__ import annotations

import itertools
import math
from pathlib import Path

import pymupdf

from peercheck.findings import Finding, Severity
from peercheck.models import Paper
from peercheck.profile import Profile, ProfileError

CHECK = "images"
BYTES_PER_MB = 1_000_000
# arXiv warns about images above 34 megapixels, about a full A4 page at 600 dpi (info.arxiv.org/help/sizes.html).
MAX_MEGAPIXELS = 34.0
# Below 50 pixels per inch a line of 10 pt text spans fewer than 7 pixels, too few for legible letters.
MIN_PPI = 50.0
# Placements below one square inch, such as icons and the bitmap letters of Type 3 fonts, hold no figure to read.
MIN_AREA = 72.0 * 72.0
# Fills and gradients are images a few pixels across.
MIN_SIDE = 16
# Text, charts, diagrams, and logos have a background color and sharp edges, unlike photos, gradients, and heat maps.
BACKGROUND_SHARE = 0.2
EDGE_STEP = 64
EDGE_SHARE = 0.005
# Larger pictures are halved until they fit, which keeps the count of sharp edges fast.
MAX_PIXELS = 1 << 18
EXAMPLES = 3


def check(paper: Paper, profile: Profile, workdir: Path) -> list[Finding]:
    """Return an error for a PDF above the file size limit, a warning for pictures placed below the resolution limit,
    and a note for images above the megapixel limit, which make the file slow to open but break no rule.

    The resolution of a placement is the lower of its pixels per inch along the two sides of the image, as pdfimages
    of poppler reports them. Only placements of one square inch or more count, and only pictures with a background
    color and sharp edges, as text, charts, diagrams, and logos have. Photos, gradients, and heat maps stay unflagged.

    Options under `images` in the profile: max_file_mb (default none): the file size limit of the venue in megabytes
    of 1,000,000 bytes. max_megapixels (default 34): the image size in megapixels above which an image is flagged.
    min_ppi (default 50): the pixels per inch below which a picture is flagged.
    """
    options = profile.options(CHECK)
    limit = _limit(options, "max_file_mb", None)
    megapixels = _limit(options, "max_megapixels", MAX_MEGAPIXELS)
    min_ppi = _limit(options, "min_ppi", MIN_PPI)
    try:
        size = Path(paper.pdf).stat().st_size
    except OSError:
        return [_error()]
    findings = _file_size(size, limit)
    try:
        with pymupdf.open(paper.pdf) as document:
            findings += _large_images(document, megapixels) + _low_resolution(document, min_ppi)
    except (RuntimeError, ValueError, pymupdf.mupdf.FzErrorBase):
        findings.append(_error())
    return findings


def _limit(options: dict, key: str, default: float | None) -> float | None:
    value = options.get(key, default)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ProfileError(f"{CHECK}.{key} must be a positive number, not {value!r}")
    return float(value)


def _file_size(size: int, limit: float | None) -> list[Finding]:
    """Return an error if the file is larger than the limit of the venue."""
    if limit is None or size <= limit * BYTES_PER_MB:
        return []
    message = f"The PDF has {size / BYTES_PER_MB:.2f} MB, above the limit of {limit:g} MB"
    return [Finding(f"{CHECK}.file-size", Severity.ERROR, message, evidence=f"{size:,} bytes")]


def _large_images(document: pymupdf.Document, limit: float) -> list[Finding]:
    """Return a note on the images above the megapixel limit, each image counted once at its first page."""
    large: dict[int, tuple[int, int, int]] = {}
    for number in range(document.page_count):
        for xref, _mask, width, height, *_ in document.get_page_images(number, full=True):
            if width * height > limit * 1e6:
                large.setdefault(xref, (number + 1, width, height))
    if not large:
        return []
    found = sorted(large.values())
    _, width, height = max(found, key=lambda item: item[1] * item[2])
    size = f"{width:,} x {height:,} pixels ({width * height / 1e6:.1f} megapixels)"
    if len(found) == 1:
        message = f"Image of {size}, above the {limit:g} megapixels at which arXiv warns"
    else:
        message = f"{len(found)} images above the {limit:g} megapixels at which arXiv warns, the largest of {size}"
    evidence = " | ".join(f"page {page}: {width:,} x {height:,} pixels" for page, width, height in found[:EXAMPLES])
    return [Finding(f"{CHECK}.megapixels", Severity.INFO, message, found[0][0], evidence)]


def _low_resolution(document: pymupdf.Document, min_ppi: float) -> list[Finding]:
    """Return a warning for the pictures placed below the resolution limit, one entry for each picture."""
    pictures: dict[tuple[int, int, float], list[tuple[int, float, float]]] = {}
    for number, page in enumerate(document, start=1):
        for info in page.get_image_info():
            a, b, c, d, _, _ = info["transform"]
            width, height = info["width"], info["height"]
            if min(width, height) < MIN_SIDE or abs(a * d - b * c) < MIN_AREA:
                continue
            across, down = math.hypot(a, b), math.hypot(c, d)
            ppi = 72 * min(width / across, height / down)
            if ppi < min_ppi and _shows_text_or_lines(page, info):
                pictures.setdefault((width, height, round(ppi, 1)), []).append((number, across / 72, down / 72))
    if not pictures:
        return []
    ranked = sorted(pictures.items(), key=lambda item: (item[0][2], item[1][0][0]))
    (width, height, ppi), places = ranked[0]
    _, across, down = places[0]
    lowest = f"{ppi:.0f} pixels per inch ({width} x {height} pixels over {across:.1f} x {down:.1f} inches)"
    if len(ranked) == 1:
        message = f"Image placed at {lowest}, too coarse for readable text and lines"
    else:
        message = (f"{len(ranked)} images placed below {min_ppi:g} pixels per inch, too coarse for readable text and "
                   f"lines, the lowest at {lowest}")
    first = min(page for _, places in ranked for page, _, _ in places)
    evidence = " | ".join(f"{_pages(places)}: {width} x {height} pixels at {ppi:.0f} ppi"
                          for (width, height, ppi), places in ranked[:EXAMPLES])
    return [Finding(f"{CHECK}.low-resolution", Severity.WARNING, message, first, evidence)]


def _shows_text_or_lines(page: pymupdf.Page, info: dict) -> bool:
    """Return True if the image of a placement has a background color and sharp edges, as text and line art have."""
    box = pymupdf.Rect(info["bbox"])
    if not box.intersects(page.rect):
        return False
    # The text extraction leaves out each image that its clip does not hold whole, and the page is the default clip.
    for block in page.get_text("dict", clip=box + (-1, -1, 1, 1), flags=pymupdf.TEXT_PRESERVE_IMAGES)["blocks"]:
        if block.get("type") == 1 and (block["width"], block["height"]) == (info["width"], info["height"]) \
                and pymupdf.Matrix(block["transform"]) == pymupdf.Matrix(info["transform"]):
            try:
                return _has_text_or_lines(pymupdf.Pixmap(block["image"]))
            except (RuntimeError, ValueError, pymupdf.mupdf.FzErrorBase):
                return False
    return False


def _has_text_or_lines(pixmap: pymupdf.Pixmap) -> bool:
    """Return True if one gray level covers BACKGROUND_SHARE of the pixels and EDGE_SHARE of neighbors differ a lot."""
    if pixmap.alpha:
        pixmap = pymupdf.Pixmap(pixmap, 0)
    if pixmap.n != 1:
        pixmap = pymupdf.Pixmap(pymupdf.csGRAY, pixmap)
    if pixmap.color_topusage()[0] < BACKGROUND_SHARE:
        return False
    while pixmap.width * pixmap.height > MAX_PIXELS:
        pixmap.shrink(1)
    data, width, stride = pixmap.samples, pixmap.width, pixmap.stride
    strong = pairs = 0
    above = b""
    for y in range(pixmap.height):
        row = data[y * stride: y * stride + width]
        strong += sum(abs(left - right) >= EDGE_STEP for left, right in itertools.pairwise(row))
        strong += sum(abs(top - bottom) >= EDGE_STEP for top, bottom in zip(above, row))
        pairs += width - 1 + len(above)
        above = row
    return pairs > 0 and strong >= EDGE_SHARE * pairs


def _pages(places: list[tuple[int, float, float]]) -> str:
    numbers = sorted({page for page, _, _ in places})
    return f"page {numbers[0]}" if len(numbers) == 1 else f"pages {', '.join(map(str, numbers))}"


def _error() -> Finding:
    return Finding(f"{CHECK}.error", Severity.WARNING, "PyMuPDF could not read the images of the PDF")

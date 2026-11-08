"""Build the PDFs of the image fixtures from their LaTeX sources with the PNG images that this script draws.

Run it from any folder with `python tests/fixtures/images/make_fixtures.py`.
"""

from __future__ import annotations

import random
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

import pymupdf

HERE = Path(__file__).resolve().parent
CODE = "@Test\npublic void testCache() {\n    assertEquals(3, cache.size());\n}"
LABELS = "stable     flaky     unclear     other"


def draw_code(dpi: int) -> bytes:
    """Return a PNG of four lines of Java code rendered at the given resolution, as a screenshot of an editor."""
    with pymupdf.open() as document:
        page = document.new_page(width=300, height=80)
        page.insert_textbox(pymupdf.Rect(8, 8, 296, 76), CODE, fontname="cour", fontsize=11)
        return page.get_pixmap(dpi=dpi).tobytes("png")


def draw_chart(dpi: int) -> bytes:
    """Return a PNG of a bar chart with axes and labels rendered at the given resolution."""
    with pymupdf.open() as document:
        page = document.new_page(width=320, height=160)
        page.draw_line((30, 140), (310, 140))
        page.draw_line((30, 140), (30, 10))
        for number, height in enumerate((110, 40, 25, 70)):
            page.draw_rect(pymupdf.Rect(50 + 65 * number, 140 - height, 90 + 65 * number, 140), color=None,
                           fill=(0.2, 0.4, 0.8))
        page.insert_text((45, 154), LABELS, fontsize=10)
        return page.get_pixmap(dpi=dpi).tobytes("png")


def draw_icon() -> bytes:
    """Return a PNG icon of 16 by 16 pixels with a filled circle."""
    with pymupdf.open() as document:
        page = document.new_page(width=16, height=16)
        page.draw_circle((8, 8), 6, color=None, fill=(0.1, 0.6, 0.2))
        return page.get_pixmap(dpi=72).tobytes("png")


def draw_shade() -> bytes:
    """Return a PNG of 64 by 48 pixels that shades from blue to red, a background without sharp edges."""
    row = b"".join(bytes((4 * x, 90, 255 - 4 * x)) for x in range(64))
    return pymupdf.Pixmap(pymupdf.csRGB, 64, 48, row * 48, False).tobytes("png")


def draw_heat_map() -> bytes:
    """Return a PNG of 40 by 50 cells in random colors, as matplotlib embeds imshow with interpolation none."""
    rng = random.Random(7)
    samples = bytes(rng.randrange(256) for _ in range(40 * 50 * 3))
    return pymupdf.Pixmap(pymupdf.csRGB, 40, 50, samples, False).tobytes("png")


def draw_scan(width: int, height: int) -> bytes:
    """Return a white bilevel PNG of the given size, which compresses to a few kilobytes at any size."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    rows = (b"\x00" + b"\xff" * ((width + 7) // 8)) * height
    header = struct.pack(">IIBBBBB", width, height, 1, 0, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(rows, 9))
            + chunk(b"IEND", b""))


IMAGES = {
    "screenshot.png": lambda: draw_code(72),
    "coarse-code.png": lambda: draw_code(30),
    "chart.png": lambda: draw_chart(144),
    "coarse-chart.png": lambda: draw_chart(40),
    "icon.png": draw_icon,
    "shade.png": draw_shade,
    "heatmap.png": draw_heat_map,
    "scan.png": lambda: draw_scan(6000, 6000),
}


def build_tex(source: Path, folder: Path) -> Path:
    """Compile one LaTeX source in the folder and copy the PDF beside the source."""
    shutil.copy(source, folder)
    subprocess.run(["pdflatex", "-interaction=nonstopmode", "-halt-on-error", source.name],
                   cwd=folder, check=True, stdout=subprocess.DEVNULL)
    target = source.with_suffix(".pdf")
    shutil.copy(folder / target.name, target)
    return target


def main() -> int:
    """Build every fixture PDF of this folder."""
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        shutil.copy(HERE / "common.tex", folder)
        for name, draw in IMAGES.items():
            (folder / name).write_bytes(draw())
        for source in sorted(HERE.glob("*.tex")):
            if source.name != "common.tex":
                print(f"built {build_tex(source, folder).name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Build the PDFs of the identity fixtures from their LaTeX sources with the figures that this script draws.

Run it from any folder with `python tests/fixtures/identity/make_fixtures.py`.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pikepdf
import pymupdf

HERE = Path(__file__).resolve().parent
# pdfTeX writes the path of the figure that it opened, and this build opens no file in a home folder.
HOME_PATH = "/Users/lbrandt/paper/figures/pipeline.pdf"
AUTHOR_BLOCK = ("Lena Brandt", "University of Nowhere", "lena.brandt@uni-nowhere.edu")
SETUP_XMP = """<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
<rdf:Description rdf:about="" xmlns:dc="http://purl.org/dc/elements/1.1/"
 xmlns:xmpMM="http://ns.adobe.com/xap/1.0/mm/" xmlns:stRef="http://ns.adobe.com/xap/1.0/sType/ResourceRef#">
<dc:creator><rdf:Seq><rdf:li>Lena Brandt</rdf:li></rdf:Seq></dc:creator>
<xmpMM:DerivedFrom stRef:filePath="/Users/lbrandt/Pictures/setup.jpg"/>
</rdf:Description></rdf:RDF></x:xmpmeta>"""


def draw_figure(path: Path, metadata: dict[str, str]) -> None:
    """Write a one-page PDF figure with a box and a label, and the given document information."""
    with pymupdf.open() as document:
        page = document.new_page(width=240, height=120)
        page.draw_rect(pymupdf.Rect(10, 10, 230, 110), color=(0, 0, 0.6))
        page.insert_text((30, 65), "Rerun the tests in shuffled orders", fontsize=10)
        document.set_metadata(metadata)
        document.save(path)


def draw_photo(path: Path, xmp: str = "") -> None:
    """Write a small JPEG photo, with the XMP packet in an APP1 segment when one is given."""
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 48, 32), False)
    pixmap.set_rect(pixmap.irect, (90, 140, 200))
    jpeg = pixmap.tobytes("jpg")
    if xmp:
        payload = b"http://ns.adobe.com/xap/1.0/\x00" + xmp.encode("utf-8")
        segment = b"\xff\xe1" + (len(payload) + 2).to_bytes(2, "big") + payload
        jpeg = jpeg[:2] + segment + jpeg[2:]
    path.write_bytes(jpeg)


def build_tex(source: Path, inputs: Path) -> Path:
    """Compile one LaTeX source in a temporary folder with the inputs and copy the PDF beside the source."""
    with tempfile.TemporaryDirectory() as tmp:
        shutil.copytree(inputs, tmp, dirs_exist_ok=True)
        shutil.copy(source, tmp)
        subprocess.run(["pdflatex", "-interaction=nonstopmode", "-halt-on-error", source.name],
                       cwd=tmp, check=True, stdout=subprocess.DEVNULL)
        target = source.with_suffix(".pdf")
        shutil.copy(Path(tmp) / target.name, target)
    return target


def move_figure_to_home_folder(pdf: Path) -> None:
    """Replace the figure path that pdfTeX wrote with the path of the figure in a home folder on macOS."""
    with pymupdf.open(pdf) as document:
        for xref in range(1, document.xref_length()):
            if "PTEX.FileName" in document.xref_get_keys(xref):
                document.xref_set_key(xref, "PTEX.FileName", pymupdf.get_pdf_str(HOME_PATH))
        data = document.tobytes(no_new_id=True)
    pdf.write_bytes(data)


def redact_author_block(pdf: Path) -> None:
    """Redact the author block and append the change to the PDF as an incremental save."""
    with pymupdf.open(pdf) as document:
        page = document[0]
        for text in AUTHOR_BLOCK:
            for rect in page.search_for(text):
                page.add_redact_annot(rect)
        page.apply_redactions()
        document.save(pdf, incremental=True, encryption=pymupdf.PDF_ENCRYPT_KEEP, no_new_id=True)


def linearize(source: Path, target: Path) -> None:
    """Save a copy of the PDF as a linearized PDF, which holds two cross-reference sections in one revision."""
    with pikepdf.open(source) as pdf:
        pdf.save(target, linearize=True, deterministic_id=True)


CHANGES = {"figure-author-home": move_figure_to_home_folder, "earlier-revision": redact_author_block}


def main() -> int:
    """Build every fixture PDF of this folder."""
    with tempfile.TemporaryDirectory() as tmp:
        inputs = Path(tmp)
        shutil.copy(HERE / "common.tex", inputs)
        draw_figure(inputs / "pipeline.pdf", {"author": "Lena Brandt", "creator": "Microsoft PowerPoint"})
        draw_figure(inputs / "plot.pdf", {"creator": "matplotlib"})
        draw_photo(inputs / "photo.jpg")
        draw_photo(inputs / "setup.jpg", SETUP_XMP)
        for source in sorted(HERE.glob("*.tex")):
            if source.name == "common.tex":
                continue
            pdf = build_tex(source, inputs)
            if source.stem in CHANGES:
                CHANGES[source.stem](pdf)
            print(f"built {pdf.name}")
    linearize(HERE / "figure-clean.pdf", HERE / "figure-clean-linearized.pdf")
    print("built figure-clean-linearized.pdf")
    return 0


if __name__ == "__main__":
    sys.exit(main())

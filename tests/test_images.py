"""Tests of the images check on the fixtures of tests/fixtures/images, built by make_fixtures.py there, on the clean
papers of PeerCheck, and on small PDFs that PyMuPDF writes."""

from __future__ import annotations

import dataclasses
import re
import shutil
import subprocess
from pathlib import Path

import pymupdf
import pytest

from peercheck.checks import images
from peercheck.findings import Severity
from peercheck.models import Paper
from peercheck.profile import ProfileError, load

FIXTURES = Path(__file__).parent / "fixtures" / "images"
PAPERS = Path(__file__).parent / "fixtures" / "papers"
FONTS = Path(__file__).parent / "fixtures" / "fonts"
SAMPLES = Path(__file__).parents[1] / "samples" / "papers"
PROFILE = load("icse-2027")
ERROR, WARNING, INFO = Severity.ERROR, Severity.WARNING, Severity.INFO
CLEAN = [*sorted(SAMPLES.glob("*.pdf")), *sorted(p for p in PAPERS.glob("*.pdf") if p.name != "corrupt.pdf"),
         FONTS / "ieee-conference.pdf", FONTS / "acm-final.pdf", FIXTURES / "clean.pdf"]
PPI = re.compile(r"(\d+) x (\d+) pixels at (\d+) ppi")
needs_pdfimages = pytest.mark.skipif(not shutil.which("pdfimages"), reason="needs pdfimages of poppler")


def run(pdf: str | Path, **options) -> list:
    """Run the check on a fixture, named without its suffix, or on a PDF, with the given images options."""
    path = pdf if isinstance(pdf, Path) else FIXTURES / f"{pdf}.pdf"
    profile = dataclasses.replace(PROFILE, checks={**PROFILE.checks, "images": options})
    return images.check(Paper(1, path), profile, path.parent)


def code_picture(dpi: int) -> bytes:
    """Return a PNG of two lines of Java code rendered at the given resolution, as a screenshot of an editor."""
    with pymupdf.open() as document:
        page = document.new_page(width=260, height=50)
        page.insert_textbox(pymupdf.Rect(6, 6, 254, 46), "@Test\nassertEquals(3, cache.size());", fontname="cour",
                            fontsize=11)
        return page.get_pixmap(dpi=dpi).tobytes("png")


def write_pdf(path: Path, *pictures: tuple[bytes, pymupdf.Rect, int, int], pages: int = 1) -> Path:
    """Write a PDF with each (PNG, place, page counted from 1, rotation) and return its path."""
    with pymupdf.open() as document:
        for _ in range(pages):
            document.new_page(width=612, height=792)
        for png, rect, number, rotation in pictures:
            document[number - 1].insert_image(rect, stream=png, rotate=rotation, keep_proportion=False)
        document.save(path)
    return path


@pytest.mark.parametrize("pdf", CLEAN, ids=lambda pdf: f"{pdf.parent.name}-{pdf.stem}")
def test_clean_paper_gives_no_finding(pdf):
    assert run(pdf) == []


def test_pictures_below_the_resolution_limit_give_one_warning_that_names_the_lowest():
    (finding,) = run("low-resolution")
    assert (finding.check, finding.severity, finding.page) == ("images.low-resolution", WARNING, 1)
    assert finding.message == ("2 images placed below 50 pixels per inch, too coarse for readable text and lines, the "
                               "lowest at 19 pixels per inch (125 x 34 pixels over 6.5 x 1.8 inches)")
    assert finding.evidence == "page 1: 125 x 34 pixels at 19 ppi | page 2: 178 x 89 pixels at 40 ppi"


def test_one_picture_below_the_limit_gives_its_size_and_placement():
    (finding,) = run("low-resolution", min_ppi=30)
    assert finding.message == ("Image placed at 19 pixels per inch (125 x 34 pixels over 6.5 x 1.8 inches), too coarse "
                               "for readable text and lines")


def test_min_ppi_of_the_profile_moves_the_limit():
    assert run("low-resolution", min_ppi=10) == []


def test_gradient_heat_map_and_icon_stay_unflagged_at_any_limit():
    (finding,) = run("clean", min_ppi=1000)
    assert finding.evidence == "page 1: 300 x 80 pixels at 72 ppi | page 1: 640 x 320 pixels at 183 ppi"


@needs_pdfimages
@pytest.mark.parametrize(("name", "limit"), [("low-resolution", 50), ("clean", 1000)])
def test_pixels_per_inch_agree_with_pdfimages_of_poppler(name, limit):
    listing = subprocess.run(["pdfimages", "-list", str(FIXTURES / f"{name}.pdf")], capture_output=True, text=True,
                             check=True).stdout.splitlines()[2:]
    listed = {(int(cells[3]), int(cells[4])): min(int(cells[12]), int(cells[13])) for cells in map(str.split, listing)}
    (finding,) = run(name, min_ppi=limit)
    found = {(int(width), int(height)): int(ppi) for width, height, ppi in PPI.findall(finding.evidence)}
    assert found and all(listed[size] == ppi for size, ppi in found.items())


def test_picture_measures_its_resolution_along_its_own_sides_when_rotated(tmp_path):
    picture = code_picture(30)
    width, height = pymupdf.Pixmap(picture).width, pymupdf.Pixmap(picture).height
    upright = write_pdf(tmp_path / "upright.pdf", (picture, pymupdf.Rect(72, 72, 72 + 4 * width, 72 + 4 * height), 1, 0))
    turned = write_pdf(tmp_path / "turned.pdf", (picture, pymupdf.Rect(72, 72, 72 + 4 * height, 72 + 4 * width), 1, 90))
    assert [f.evidence for f in run(upright)] == [f"page 1: {width} x {height} pixels at 18 ppi"]
    assert [f.evidence for f in run(turned)] == [f"page 1: {width} x {height} pixels at 18 ppi"]


def test_picture_partly_outside_the_page_is_measured(tmp_path):
    pdf = write_pdf(tmp_path / "partly.pdf", (code_picture(30), pymupdf.Rect(300, 72, 840, 172), 1, 0))
    assert [f.check for f in run(pdf)] == ["images.low-resolution"]


def test_coarse_picture_smaller_than_a_square_inch_gives_no_finding(tmp_path):
    picture = code_picture(30)
    small = write_pdf(tmp_path / "small.pdf", (picture, pymupdf.Rect(72, 72, 132, 82), 1, 0))
    large = write_pdf(tmp_path / "large.pdf", (picture, pymupdf.Rect(72, 72, 432, 132), 1, 0))
    assert run(small) == []
    assert [f.check for f in run(large)] == ["images.low-resolution"]


def test_picture_placed_outside_the_page_gives_no_finding(tmp_path):
    pdf = write_pdf(tmp_path / "outside.pdf", (code_picture(30), pymupdf.Rect(700, 72, 1060, 132), 1, 0))
    assert run(pdf) == []


def test_same_picture_on_two_pages_counts_once_with_both_pages(tmp_path):
    picture, rect = code_picture(30), pymupdf.Rect(72, 72, 432, 132)
    pdf = write_pdf(tmp_path / "twice.pdf", (picture, rect, 1, 0), (picture, rect, 2, 0), pages=2)
    (finding,) = run(pdf)
    assert finding.message.startswith("Image placed at 22 pixels per inch (109 x 21 pixels over 5.0 x 0.8 inches)")
    assert (finding.page, finding.evidence) == (1, "pages 1, 2: 109 x 21 pixels at 22 ppi")


def test_image_above_34_megapixels_gives_an_info_note():
    (finding,) = run("megapixels")
    assert (finding.check, finding.severity, finding.page) == ("images.megapixels", INFO, 1)
    assert finding.message == ("Image of 6,000 x 6,000 pixels (36.0 megapixels), above the 34 megapixels at which "
                               "arXiv warns")


def test_max_megapixels_of_the_profile_moves_the_limit():
    assert run("megapixels", max_megapixels=40) == []


def test_several_large_images_are_counted_once_each_with_the_largest_named(tmp_path):
    chart, code = code_picture(150), code_picture(100)
    rect = pymupdf.Rect(72, 72, 312, 112)
    pdf = write_pdf(tmp_path / "large.pdf", (chart, rect, 2, 0), (code, rect, 1, 0), (chart, rect, 3, 0), pages=3)
    (finding,) = run(pdf, max_megapixels=0.01)
    width, height = pymupdf.Pixmap(chart).width, pymupdf.Pixmap(chart).height
    assert finding.page == 1
    assert finding.message.startswith(f"2 images above the 0.01 megapixels at which arXiv warns, the largest of "
                                      f"{width:,} x {height:,} pixels")


def test_file_above_the_size_limit_of_the_profile_gives_an_error():
    size = (FIXTURES / "clean.pdf").stat().st_size
    (finding,) = run("clean", max_file_mb=0.01)
    assert (finding.check, finding.severity) == ("images.file-size", ERROR)
    assert finding.message == f"The PDF has {size / 1e6:.2f} MB, above the limit of 0.01 MB"
    assert finding.evidence == f"{size:,} bytes"


def test_file_within_the_size_limit_of_the_profile_gives_no_finding():
    assert run("clean", max_file_mb=50) == []


@pytest.mark.parametrize("value", ["fifty", 0, -5, True, [50]])
def test_limit_that_is_no_positive_number_raises_a_profile_error(value):
    with pytest.raises(ProfileError):
        run("clean", min_ppi=value)


def test_unreadable_pdf_gives_a_warning_that_names_no_path_or_file(tmp_path):
    bad = tmp_path / "icse2027-paper7.pdf"
    bad.write_bytes(b"not a pdf at all")
    for pdf in (bad, tmp_path / "icse2027-paper8.pdf", PAPERS / "corrupt.pdf"):
        (finding,) = run(pdf)
        assert (finding.check, finding.severity) == ("images.error", WARNING)
        assert str(pdf.parent) not in finding.message and pdf.name not in finding.message


def test_pdf_locked_with_a_password_gives_a_warning(tmp_path):
    with pymupdf.open(FIXTURES / "low-resolution.pdf") as document:
        document.save(tmp_path / "locked.pdf", encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="user",
                      owner_pw="owner")
    assert [(f.check, f.severity) for f in run(tmp_path / "locked.pdf")] == [("images.error", WARNING)]

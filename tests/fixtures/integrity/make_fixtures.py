"""Build the PDFs of the integrity fixtures, a clean paper.pdf from paper.tex and encrypted and damaged copies of it.

Run it from any folder with `python tests/fixtures/integrity/make_fixtures.py`.
"""

from __future__ import annotations

import io
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pikepdf

HERE = Path(__file__).resolve().parent
OWNER_PASSWORD = "author"
USER_PASSWORD = "reviewer"


def build_paper() -> bytes:
    """Compile paper.tex in a temporary folder and return the PDF."""
    with tempfile.TemporaryDirectory() as tmp:
        shutil.copy(HERE / "paper.tex", tmp)
        subprocess.run(["pdflatex", "-interaction=nonstopmode", "-halt-on-error", "paper.tex"],
                       cwd=tmp, check=True, stdout=subprocess.DEVNULL)
        return (Path(tmp) / "paper.pdf").read_bytes()


def encrypt(data: bytes, encryption: pikepdf.Encryption) -> bytes:
    """Return the PDF saved with the given passwords and permissions."""
    target = io.BytesIO()
    with pikepdf.open(io.BytesIO(data)) as pdf:
        pdf.save(target, encryption=encryption)
    return target.getvalue()


def misplace_cross_reference(data: bytes) -> bytes:
    """Point startxref at an offset past the end of the file, which readers repair by scanning the objects."""
    return data[: data.rindex(b"startxref")] + b"startxref\n999999\n%%EOF\n"


def duplicate_key(data: bytes) -> bytes:
    """Give the document information two /Title keys, which qpdf reports and MuPDF reads without a repair."""
    target = io.BytesIO()
    with pikepdf.open(io.BytesIO(data)) as pdf:
        pdf.docinfo["/Title"] = "Ranking"
        pdf.docinfo["/Xitle"] = "Flaky"
        pdf.save(target, compress_streams=False, object_stream_mode=pikepdf.ObjectStreamMode.disable)
    # A name of the same length keeps every offset of the cross-reference table right.
    return target.getvalue().replace(b"/Xitle", b"/Title")


def main() -> int:
    """Build every fixture PDF of this folder."""
    paper = build_paper()
    no_print_or_copy = pikepdf.Permissions(print_lowres=False, print_highres=False, extract=False)
    fixtures = {
        "paper.pdf": paper,
        "user-password.pdf": encrypt(paper, pikepdf.Encryption(owner=OWNER_PASSWORD, user=USER_PASSWORD)),
        "owner-password.pdf": encrypt(paper, pikepdf.Encryption(owner=OWNER_PASSWORD, user="", allow=no_print_or_copy)),
        "cut.pdf": paper[: len(paper) // 2],
        "broken-xref.pdf": misplace_cross_reference(paper),
        "duplicate-key.pdf": duplicate_key(paper),
    }
    for name, data in fixtures.items():
        (HERE / name).write_bytes(data)
        print(f"built {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

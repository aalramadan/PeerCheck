"""Build the PDFs of the unresolved-reference fixtures, compiled once as a broken build leaves them or in full.

Run it from any folder with `python tests/fixtures/unresolved/make_fixtures.py`.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ASSETS = ("body.tex", "refs.bib")
# Each fixture PDF with its source, its engine, and whether BibTeX and two more runs follow the first.
BUILDS = {
    "ieee-once.pdf": ("ieee.tex", "pdflatex", False),
    "ieee.pdf": ("ieee.tex", "pdflatex", True),
    "ieee-missing.pdf": ("ieee-missing.tex", "pdflatex", True),
    "acm-once.pdf": ("acm.tex", "pdflatex", False),
    "lualatex-once.pdf": ("lualatex.tex", "lualatex", False),
}


def build(source: str, engine: str, full: bool, target: Path) -> None:
    """Compile one LaTeX source in a temporary folder and copy its PDF to the target."""
    with tempfile.TemporaryDirectory() as tmp:
        for name in ASSETS + (source,):
            shutil.copy(HERE / name, tmp)
        stem = Path(source).stem
        latex = [engine, "-interaction=nonstopmode", "-halt-on-error", source]
        steps = [latex, ["bibtex", stem], latex, latex] if full else [latex]
        for step in steps:
            subprocess.run(step, cwd=tmp, check=True, stdout=subprocess.DEVNULL)
        shutil.copy(Path(tmp) / f"{stem}.pdf", target)


def main() -> int:
    """Build every fixture PDF of this folder."""
    for name, (source, engine, full) in BUILDS.items():
        build(source, engine, full, HERE / name)
        print(f"built {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

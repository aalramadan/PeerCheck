"""Build the PDFs of the active-content fixtures from their LaTeX sources, each compiled twice with pdflatex.

Run it from any folder with `python tests/fixtures/active/make_fixtures.py`.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
# The data file that clean.tex attaches to its PDF.
ATTACHED_DATA = "test,orders,label\ntestCache,100,flaky\ntestParse,100,stable\n"


def build_tex(source: Path, folder: Path) -> Path:
    """Compile one LaTeX source twice in the folder, for the references and the animation, and copy the PDF beside
    the source."""
    shutil.copy(source, folder)
    for _ in range(2):
        subprocess.run(["pdflatex", "-interaction=nonstopmode", "-halt-on-error", source.name],
                       cwd=folder, check=True, stdout=subprocess.DEVNULL)
    target = source.with_suffix(".pdf")
    shutil.copy(folder / target.name, target)
    return target


def main() -> int:
    """Build every fixture PDF of this folder."""
    for source in sorted(HERE.glob("*.tex")):
        if source.name == "common.tex":
            continue
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            shutil.copy(HERE / "common.tex", folder)
            (folder / "tests.csv").write_text(ATTACHED_DATA, encoding="utf-8")
            print(f"built {build_tex(source, folder).name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

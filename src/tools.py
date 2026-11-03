"""Locations of the programs and the tools in external/ that the checks run, and a report of what is missing."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

INSTALL_HINTS = {
    "perl": "install Perl (Debian/Ubuntu: apt install perl; macOS: it ships with the system)",
    "pdftohtml": "install poppler (Debian/Ubuntu: apt install poppler-utils; macOS: brew install poppler)",
    "java": "install Java 11 or newer (Debian/Ubuntu: apt install default-jre; macOS: brew install openjdk)",
}


class ToolError(RuntimeError):
    """A program or a file of external/ that a check needs is missing."""


# The tools and data of other authors sit in external/ at the root of the repository, beside src/.
EXTERNAL = Path(__file__).resolve().parent.parent / "external"


def external(relative: str) -> Path:
    """Return the path of a file under external/."""
    return EXTERNAL / relative


def banal() -> Path:
    """Return the path of the banal script of HotCRP."""
    return external("hotcrp/banal")


def submission_checker() -> Path:
    """Return the path of the jar of the revised SIGSOFT submission checker."""
    return external("submission-checker/submission-checker.jar")


def program(name: str) -> str:
    """Return the full path of a program on the PATH, or raise with an install hint."""
    found = shutil.which(name)
    if not found:
        raise ToolError(f"{name} not found: {INSTALL_HINTS.get(name, 'install it and add it to the PATH')}")
    return found


def cache_dir() -> Path:
    """Return the folder where PeerCheck keeps downloaded models, databases, and tools."""
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return Path(base) / "peercheck"


def missing() -> dict[str, str]:
    """Return each program or file of external/ that is missing, with its install hint."""
    problems = {name: hint for name, hint in INSTALL_HINTS.items() if not shutil.which(name)}
    for path in (banal(), submission_checker()):
        if not path.is_file():
            problems[path.name] = f"file missing at {path}; run PeerCheck from a full clone of the repository"
    return problems

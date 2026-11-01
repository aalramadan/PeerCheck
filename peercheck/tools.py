"""Locations of the external programs and bundled tools that the checks run, and a report of what is missing."""

from __future__ import annotations

import os
import shutil
from importlib import resources
from pathlib import Path

INSTALL_HINTS = {
    "perl": "install Perl (Debian/Ubuntu: apt install perl; macOS: it ships with the system)",
    "pdftohtml": "install poppler (Debian/Ubuntu: apt install poppler-utils; macOS: brew install poppler)",
    "java": "install Java 11 or newer (Debian/Ubuntu: apt install default-jre; macOS: brew install openjdk)",
}


class ToolError(RuntimeError):
    """A program or a bundled file that a check needs is missing."""


def vendor(relative: str) -> Path:
    """Return the path of a file bundled under peercheck/vendor."""
    return Path(str(resources.files("peercheck") / "vendor" / relative))


def banal() -> Path:
    """Return the path of the bundled banal script."""
    return vendor("banal/banal")


def submission_checker() -> Path:
    """Return the path of the bundled SIGSOFT submission checker jar."""
    return vendor("submission-checker/submission-checker.jar")


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
    """Return each program or bundled file that is missing, with its install hint."""
    problems = {name: hint for name, hint in INSTALL_HINTS.items() if not shutil.which(name)}
    for path in (banal(), submission_checker()):
        if not path.is_file():
            problems[path.name] = f"bundled file missing at {path}; reinstall PeerCheck"
    return problems

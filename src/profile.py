"""Venue profiles that set the limits and the options of every check."""

from __future__ import annotations

import re
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

import yaml

PAGE_NUMBER_POLICIES = ("ignore", "warning", "error")
TOP_KEYS = {"name", "source", "submission_system", "file_pattern", "id_column", "format", "checks"}
FORMAT_KEYS = {
    "style", "paper_size", "paper_size_tolerance", "columns", "main_pages", "reference_pages", "margins",
    "margin_tolerance", "body_font_max", "reference_font_min", "page_numbers", "required_headings",
    "require_abstract",
}


class ProfileError(ValueError):
    """A profile that misses a key, holds an unknown key, or sets a wrong value."""


@dataclass(frozen=True)
class FormatRules:
    """Page, paper, margin, font, and heading limits of a venue."""

    style: str
    paper_size: tuple[float, float]
    paper_size_tolerance: float
    columns: int
    main_pages: int
    reference_pages: int
    margins: tuple[float, float, float, float] | None
    margin_tolerance: float
    body_font_max: float
    reference_font_min: float
    page_numbers: str
    required_headings: tuple[str, ...]
    require_abstract: bool


@dataclass(frozen=True)
class Profile:
    """Everything PeerCheck needs to know about one venue."""

    key: str
    name: str
    source: str
    submission_system: str
    file_pattern: str
    id_column: str
    format: FormatRules
    checks: dict[str, dict[str, Any]]

    def paper_id(self, filename: str) -> int | None:
        """Return the paper ID in a file name, or None if the name does not match the pattern."""
        match = re.search(self.file_pattern, filename, re.IGNORECASE)
        return int(match.group(1)) if match else None

    def options(self, check: str) -> dict[str, Any]:
        """Return the options of one check, empty if the profile sets none."""
        return self.checks.get(check) or {}


def available() -> list[str]:
    """Return the keys of the profiles that ship with PeerCheck."""
    folder = resources.files("peercheck") / "profiles"
    return sorted(item.name[: -len(".yaml")] for item in folder.iterdir() if item.name.endswith(".yaml"))


def load(name_or_path: str) -> Profile:
    """Load a shipped profile by its key, such as icse-2027, or a profile file by its path."""
    path = Path(name_or_path)
    if path.suffix in (".yaml", ".yml") and path.is_file():
        return parse(yaml.safe_load(path.read_text(encoding="utf-8")), path.stem)
    resource = resources.files("peercheck") / "profiles" / f"{name_or_path}.yaml"
    if not resource.is_file():
        raise ProfileError(f"unknown profile {name_or_path!r}; shipped profiles: {', '.join(available())}")
    return parse(yaml.safe_load(resource.read_text(encoding="utf-8")), name_or_path)


def parse(data: Any, key: str) -> Profile:
    """Check the keys and the values of a loaded profile and return the profile."""
    if not isinstance(data, dict):
        raise ProfileError(f"profile {key}: the file must hold a mapping")
    _keys(data, TOP_KEYS, TOP_KEYS - {"checks"}, f"profile {key}")
    rules = data["format"]
    if not isinstance(rules, dict):
        raise ProfileError(f"profile {key}: format must be a mapping")
    _keys(rules, FORMAT_KEYS, FORMAT_KEYS - {"margins", "require_abstract"}, f"profile {key}, format")
    pattern = str(data["file_pattern"])
    try:
        groups = re.compile(pattern).groups
    except re.error as exc:
        raise ProfileError(f"profile {key}: file_pattern does not compile ({exc})") from exc
    if groups != 1:
        raise ProfileError(f"profile {key}: file_pattern needs exactly one group for the paper ID")
    if rules["page_numbers"] not in PAGE_NUMBER_POLICIES:
        raise ProfileError(f"profile {key}: page_numbers must be one of {', '.join(PAGE_NUMBER_POLICIES)}")
    checks = data.get("checks") or {}
    if not isinstance(checks, dict):
        raise ProfileError(f"profile {key}: checks must be a mapping")
    return Profile(
        key=key,
        name=str(data["name"]),
        source=str(data["source"]),
        submission_system=str(data["submission_system"]),
        file_pattern=pattern,
        id_column=str(data["id_column"]),
        format=FormatRules(
            style=str(rules["style"]),
            paper_size=_numbers(rules["paper_size"], 2, key, "paper_size"),
            paper_size_tolerance=float(rules["paper_size_tolerance"]),
            columns=int(rules["columns"]),
            main_pages=int(rules["main_pages"]),
            reference_pages=int(rules["reference_pages"]),
            margins=None if rules.get("margins") is None else _numbers(rules["margins"], 4, key, "margins"),
            margin_tolerance=float(rules["margin_tolerance"]),
            body_font_max=float(rules["body_font_max"]),
            reference_font_min=float(rules["reference_font_min"]),
            page_numbers=str(rules["page_numbers"]),
            required_headings=tuple(str(h).lower() for h in rules["required_headings"] or ()),
            require_abstract=bool(rules.get("require_abstract", True)),
        ),
        checks={str(name): dict(options or {}) for name, options in checks.items()},
    )


def _keys(data: dict, allowed: set[str], required: set[str], where: str) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ProfileError(f"{where}: unknown keys {', '.join(unknown)}")
    missing = sorted(required - set(data))
    if missing:
        raise ProfileError(f"{where}: missing keys {', '.join(missing)}")


def _numbers(value: Any, size: int, key: str, name: str) -> tuple:
    if not isinstance(value, (list, tuple)) or len(value) != size:
        raise ProfileError(f"profile {key}: {name} must list {size} numbers")
    return tuple(float(v) for v in value)

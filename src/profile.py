"""Templates, the files that set the rules of a venue and the options of every check."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

PAGE_NUMBER_POLICIES = ("ignore", "warning", "error")
TOP_KEYS = {"name", "source", "file_pattern", "id_column", "format", "checks"}
REQUIRED_TOP_KEYS = {"name", "source", "format"}
# The shipped file that lists every option for a new venue, which holds no values of its own.
DEFAULT = "default"
# Conference systems name a downloaded PDF with its number after paper or submission, such as CONF_2027_paper_12.pdf
# or conf27-paper12.pdf. A name may also be the number alone, such as 12.pdf.
PAPER_NUMBER = (re.compile(r"(?:paper|submission)[\W_]*(\d+)", re.IGNORECASE),
                re.compile(r"^#?(\d+)\.pdf$", re.IGNORECASE))
FORMAT_KEYS = {
    "style", "paper_size", "paper_size_tolerance", "columns", "main_pages", "reference_pages", "margins",
    "margin_tolerance", "body_font_max", "body_font_min", "leading_min", "reference_font_min", "page_numbers",
    "required_headings", "require_abstract", "exempt_sections", "exempt_pages_max",
}
# A venue sets only the rules it states. Each other rule keeps its default, or goes unchecked when it has none.
OPTIONAL_FORMAT_KEYS = {"paper_size_tolerance", "margins", "margin_tolerance", "body_font_max", "body_font_min",
                        "leading_min", "reference_font_min", "page_numbers", "required_headings", "require_abstract",
                        "exempt_sections", "exempt_pages_max"}
# A wheel holds the shipped templates in peercheck/templates/, and a source checkout keeps them in templates/ beside src/.
_PACKAGE = Path(__file__).resolve().parent
PROFILES = _PACKAGE / "templates" if (_PACKAGE / "templates").is_dir() else _PACKAGE.parent / "templates"
# Options of the checks that hold a list of strings.
LIST_OPTIONS = {"anonymity": ("allowed_hosts",), "hidden_text": ("extra_phrases",)}


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
    body_font_max: float | None
    body_font_min: float | None
    leading_min: float | None
    reference_font_min: float | None
    page_numbers: str
    required_headings: tuple[str, ...]
    require_abstract: bool
    exempt_sections: tuple[str, ...] = ()
    exempt_pages_max: float | None = None


@dataclass(frozen=True)
class Profile:
    """Everything PeerCheck needs to know about one venue."""

    key: str
    name: str
    source: str
    file_pattern: str | None
    id_column: str | None
    format: FormatRules
    checks: dict[str, dict[str, Any]]

    def paper_id(self, filename: str) -> int | None:
        """Return the paper number in a file name, or None if the name holds none."""
        return paper_number(filename, self.file_pattern)

    def options(self, check: str) -> dict[str, Any]:
        """Return the options of one check, empty if the profile sets none."""
        return self.checks.get(check) or {}


def paper_number(filename: str, pattern: str | None = None) -> int | None:
    """Return the paper number in a file name through a pattern of a profile, else through the forms of the systems."""
    for regex in (re.compile(pattern, re.IGNORECASE),) if pattern else PAPER_NUMBER:
        match = regex.search(filename)
        if match:
            return int(match.group(1))
    return None


def available() -> list[str]:
    """Return the keys of the filled profiles that ship with PeerCheck."""
    return sorted(item.stem for item in PROFILES.glob("*.yaml") if item.stem != DEFAULT)


def load(name_or_path: str) -> Profile:
    """Load a shipped profile by its key, such as icse-2027, or a profile file by its path."""
    path = Path(name_or_path)
    if path.suffix in (".yaml", ".yml") and path.is_file():
        return parse(yaml.safe_load(path.read_text(encoding="utf-8")), path.stem)
    resource = PROFILES / f"{name_or_path}.yaml"
    if not resource.is_file():
        raise ProfileError(f"unknown template {name_or_path!r}; shipped templates: {', '.join(available())}")
    return parse(yaml.safe_load(resource.read_text(encoding="utf-8")), name_or_path)


def parse(data: Any, key: str) -> Profile:
    """Check the keys and the values of a loaded profile and return the profile."""
    if data is None:
        raise ProfileError(f"template {key} holds no values; copy templates/{DEFAULT}.yaml and set the rules of the venue")
    if not isinstance(data, dict):
        raise ProfileError(f"template {key}: the file must hold a mapping")
    _keys(data, TOP_KEYS, REQUIRED_TOP_KEYS, f"template {key}")
    rules = data["format"]
    if not isinstance(rules, dict):
        raise ProfileError(f"template {key}: format must be a mapping")
    _keys(rules, FORMAT_KEYS, FORMAT_KEYS - OPTIONAL_FORMAT_KEYS, f"template {key}, format")
    pattern = None if data.get("file_pattern") is None else str(data["file_pattern"])
    if pattern is not None:
        try:
            groups = re.compile(pattern).groups
        except re.error as exc:
            raise ProfileError(f"template {key}: file_pattern does not compile ({exc})") from exc
        if groups != 1:
            raise ProfileError(f"template {key}: file_pattern needs exactly one group for the paper ID")
    if rules.get("page_numbers", "ignore") not in PAGE_NUMBER_POLICIES:
        raise ProfileError(f"template {key}: page_numbers must be one of {', '.join(PAGE_NUMBER_POLICIES)}")
    checks = data.get("checks") or {}
    if not isinstance(checks, dict):
        raise ProfileError(f"template {key}: checks must be a mapping")
    return Profile(
        key=key,
        name=str(data["name"]),
        source=str(data["source"]),
        file_pattern=pattern,
        id_column=None if data.get("id_column") is None else str(data["id_column"]),
        format=FormatRules(
            style=str(rules["style"]),
            paper_size=_numbers(rules["paper_size"], 2, key, "paper_size"),
            paper_size_tolerance=float(rules.get("paper_size_tolerance", 5)),
            columns=int(rules["columns"]),
            main_pages=int(rules["main_pages"]),
            reference_pages=int(rules["reference_pages"]),
            margins=None if rules.get("margins") is None else _numbers(rules["margins"], 4, key, "margins"),
            margin_tolerance=float(rules.get("margin_tolerance", 18)),
            body_font_max=_optional_number(rules.get("body_font_max")),
            body_font_min=_optional_number(rules.get("body_font_min")),
            leading_min=_optional_number(rules.get("leading_min")),
            reference_font_min=_optional_number(rules.get("reference_font_min")),
            page_numbers=str(rules.get("page_numbers", "ignore")),
            required_headings=tuple(
                h.lower() for h in strings(rules.get("required_headings"), f"template {key}: required_headings")),
            require_abstract=bool(rules.get("require_abstract", True)),
            exempt_sections=tuple(
                s.lower() for s in strings(rules.get("exempt_sections"), f"template {key}: exempt_sections")),
            exempt_pages_max=_optional_number(rules.get("exempt_pages_max")),
        ),
        checks={str(name): _check_options(str(name), options, f"template {key}: checks.{name}")
                for name, options in checks.items()},
    )


def strings(value: Any, where: str) -> tuple[str, ...]:
    """Return a list of a profile as strings, where one string is a list of one and nothing an empty list."""
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple)) and all(isinstance(item, (str, int, float)) for item in value):
        return tuple(str(item) for item in value)
    raise ProfileError(f"{where} must be a string or a list of strings")


def _check_options(name: str, options: Any, where: str) -> dict[str, Any]:
    """Return the options of one check, where true or false alone switches the check on or off."""
    if options is None:
        return {}
    if isinstance(options, bool):
        return {"enabled": options}
    if not isinstance(options, dict):
        raise ProfileError(f"{where} must be a mapping, true, or false")
    if not isinstance(options.get("enabled", True), bool):
        raise ProfileError(f"{where}.enabled must be true or false")
    lists = {option: list(strings(options[option], f"{where}.{option}"))
             for option in LIST_OPTIONS.get(name, ()) if option in options}
    return {**options, **lists}


def _keys(data: dict, allowed: set[str], required: set[str], where: str) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ProfileError(f"{where}: unknown keys {', '.join(unknown)}")
    missing = sorted(required - set(data))
    if missing:
        raise ProfileError(f"{where}: missing keys {', '.join(missing)}")


def _numbers(value: Any, size: int, key: str, name: str) -> tuple:
    if not isinstance(value, (list, tuple)) or len(value) != size:
        raise ProfileError(f"template {key}: {name} must list {size} numbers")
    return tuple(float(v) for v in value)


def _optional_number(value: Any) -> float | None:
    return None if value is None else float(value)

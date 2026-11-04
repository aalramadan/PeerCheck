"""Findings that every check reports, each with a severity to sort by."""

from __future__ import annotations

import enum
from dataclasses import dataclass


class Severity(enum.Enum):
    """How much a finding matters for the decision on a paper or a review."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True)
class Finding:
    """One result of one check for one paper or one review."""

    check: str
    severity: Severity
    message: str
    page: int | None = None
    evidence: str = ""

    def as_text(self) -> str:
        """Return the finding as one line for a report cell."""
        where = f" (page {self.page})" if self.page else ""
        return f"{self.severity.value.upper()}: {self.message}{where}"


def needs_review(findings: list[Finding]) -> bool:
    """Return True if any finding is an error or a warning."""
    return any(f.severity is not Severity.INFO for f in findings)


def count(findings: list[Finding], severity: Severity) -> int:
    """Return the number of findings of one severity."""
    return sum(1 for f in findings if f.severity is severity)

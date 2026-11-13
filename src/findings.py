"""Findings that every check reports, each with a severity to sort by."""

from __future__ import annotations

import enum
from dataclasses import dataclass

# The most characters of the text that a finding shows as its evidence.
EVIDENCE_LIMIT = 120


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
        """Return the finding as one line for a report cell, such as ERROR layout.pages: 12 main pages (page 12)."""
        where = f" (page {self.page})" if self.page else ""
        return f"{self.severity.value.upper()} {self.check}: {self.message}{where}"


def excerpt(text: str, limit: int = EVIDENCE_LIMIT) -> str:
    """Return a text on one line for the evidence of a finding, cut with an ellipsis at the limit."""
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def needs_review(findings: list[Finding]) -> bool:
    """Return True if any finding is an error or a warning."""
    return any(f.severity is not Severity.INFO for f in findings)


def count(findings: list[Finding], severity: Severity) -> int:
    """Return the number of findings of one severity."""
    return sum(1 for f in findings if f.severity is severity)

"""Papers, people, and reviews as the checks see them."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Person:
    """An author, a reviewer, or a program committee member."""

    first: str
    last: str
    email: str = ""
    affiliation: str = ""
    dblp: str = ""

    @property
    def name(self) -> str:
        """Return the first and last name joined by a space."""
        return f"{self.first} {self.last}".strip()


@dataclass(frozen=True)
class Paper:
    """One submission with its PDF and, where the export holds them, its title and authors."""

    paper_id: int
    pdf: Path
    title: str = ""
    authors: tuple[Person, ...] = ()


@dataclass(frozen=True)
class Review:
    """One review with its scores, its text fields, and the text meant for the authors."""

    review_id: str
    paper_id: int | None
    title: str
    source: str
    scores: dict[str, str] = field(default_factory=dict)
    fields: dict[str, str] = field(default_factory=dict)
    author_text: str = ""
    reviewer: Person | None = None

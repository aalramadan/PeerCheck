"""Keeps the records that an open index returns for a title between runs, as Hallucinator keeps the answers of its
sources: a title with records for seven days and a title without one for a day."""

from __future__ import annotations

import dataclasses
import json
import time
from pathlib import Path

from peercheck.papers.open_indexes import Work

DAY = 86400.0
FOUND_DAYS, EMPTY_DAYS = 7, 1


class LookupCache:
    """The answers of the open indexes by source and title, read from a file and written back by save."""

    def __init__(self, path: Path):
        self.path = path
        self.answers: dict[str, tuple[float, list[Work]]] = {}
        try:
            kept = json.loads(path.read_text(encoding="utf-8"))
            for key, (asked, works) in kept.items():
                if time.time() - asked < (FOUND_DAYS if works else EMPTY_DAYS) * DAY:
                    self.answers[key] = (asked, [Work(title, tuple(authors), container)
                                                 for title, authors, container in works])
        except (OSError, ValueError, TypeError, AttributeError):
            self.answers = {}

    def works(self, source: str, title: str, lookup) -> list[Work]:
        """Return the records of a source for a title from the file, or else from the lookup, whose error passes
        on and keeps nothing."""
        key = f"{source}\n{title}"
        if key not in self.answers:
            self.answers[key] = (time.time(), lookup(title))
        return self.answers[key][1]

    def save(self) -> None:
        """Write the answers to the file. A file that cannot be written leaves the next run without them."""
        rows = {key: (asked, [dataclasses.astuple(work) for work in works])
                for key, (asked, works) in self.answers.items()}
        partial = self.path.with_suffix(".partial")
        try:
            partial.write_text(json.dumps(rows), encoding="utf-8")
            partial.replace(self.path)
        except OSError:
            partial.unlink(missing_ok=True)

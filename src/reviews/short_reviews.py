"""Reviews of one or two sentences, which the reviewer rules of EMNLP 2025 flag when they give no constructive
feedback, as those of CVPR 2026 flag unreasonably short reviews. A review with fewer sentences for the authors than
min_sentences (template key "short_reviews", default 3) gets short_reviews.few-sentences (INFO)."""

from __future__ import annotations

import re

from peercheck.findings import Finding, Severity
from peercheck.models import Review

CHECK = "short_reviews.few-sentences"
DEFAULTS = {"min_sentences": 3}
# An abbreviation such as e.g. may count as an end, which only makes a review look longer.
_END = re.compile(r"[.!?]+[\"”’')\]]*(?=\s|$)|[。！？।॥]+|\n+")


def check_reviews(reviews: list[Review], options: dict) -> dict[str, list[Finding]]:
    """Return a note on each review whose text for the authors holds fewer sentences than min_sentences."""
    least = int({**DEFAULTS, **(options or {})}["min_sentences"])
    findings: dict[str, list[Finding]] = {review.review_id: [] for review in reviews}
    for review in reviews:
        count = sentences(review.author_text)
        if count < least:
            size = f"{count} sentence{'' if count == 1 else 's'}" if count else "no text"
            findings[review.review_id].append(Finding(CHECK, Severity.INFO, f"The review has {size} for the authors"))
    return findings


def sentences(text: str) -> int:
    """Count the sentences and the list items of a text, each a run of words up to a full stop or a line break."""
    return sum(1 for part in _END.split(text) if re.search(r"\w", part))

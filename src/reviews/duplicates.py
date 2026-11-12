"""Near-duplicate paragraphs across the reviews of a venue, found with MinHash LSH.

The check follows the MinHash LSH search of Day (Scientometrics 2022, arXiv:2202.03310), which
found referee comments copied across referee accounts of 19 SAGE journals. Each paragraph of
Review.author_text becomes a set of character shingles of its lowercase words, in any script. A
MinHash LSH index of datasketch (github.com/ekzhu/datasketch, MIT) proposes candidate pairs from
half the threshold, and the exact Jaccard similarity of the two shingle sets decides. A pair of
paragraphs from two different reviews at or above the threshold gives duplicates.near-duplicate
(WARNING) on both reviews, with the other review, the two paragraphs, and the similarity as
evidence. A flag asks a person to read the two reviews, since a reviewer may reuse a personal
template or two reviewers may quote the same passage of the paper.

A paragraph is a block of text between blank lines. A list item inside a block starts a paragraph
of its own, and the wrapped lines of a block join into one paragraph.

Options (profile key "duplicates"):

- threshold (0.5): the Jaccard similarity at or above which two paragraphs count as near
  duplicates. Day reports that pairs of referee comments with a Jaccard similarity above 0.5 are
  very rare (Search 2, on sets of sentences). The check applies the same value to shingle sets.
- shingle (5): characters per shingle, the size of Day's MinHash LSH example (Search 3).
- min_chars (150): paragraphs shorter than this many characters are skipped, the length below which
  Day removed comments.
- num_perm (128): MinHash permutations, the default of datasketch.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from datasketch import MinHash, MinHashLSH

from peercheck.dblp import fold
from peercheck.findings import Finding, Severity
from peercheck.models import Person, Review

CHECK = "duplicates.near-duplicate"
DEFAULTS = {"threshold": 0.5, "shingle": 5, "min_chars": 150, "num_perm": 128}
_BLOCK = re.compile(r"\n\s*\n")
_ITEM = re.compile(r"^\s*(?:[-*•●]|\d{1,2}[.)]|\([a-z0-9]{1,3}\))\s+")
_WORD = re.compile(r"[^\W_]+")


@dataclass(frozen=True)
class _Paragraph:
    review: int
    number: int
    shingles: frozenset[str]


def check_reviews(reviews: list[Review], options: dict) -> dict[str, list[Finding]]:
    """Return a near-duplicate finding on both reviews of each pair that shares a near-duplicate paragraph."""
    settings = {**DEFAULTS, **(options or {})}
    threshold = float(settings["threshold"])
    if not 0 < threshold <= 1:
        raise ValueError(f"duplicates: threshold must lie in (0, 1], not {threshold}")
    items = [
        _Paragraph(r, n, _shingles(text, int(settings["shingle"])))
        for r, review in enumerate(reviews)
        for n, text in enumerate(paragraphs(review.author_text), start=1)
        if len(_words(text)) >= int(settings["min_chars"])
    ]
    matches: dict[tuple[int, int], list[tuple[int, int, float]]] = {}
    for a, b, similarity in _similar_pairs(items, threshold, int(settings["num_perm"])):
        first, second = items[a], items[b]
        matches.setdefault((first.review, second.review), []).append((first.number, second.number, similarity))
    findings: dict[str, list[Finding]] = {review.review_id: [] for review in reviews}
    for (r1, r2), pairs in sorted(matches.items()):
        findings[reviews[r1].review_id].append(_finding(reviews[r1], reviews[r2], pairs))
        findings[reviews[r2].review_id].append(_finding(reviews[r2], reviews[r1], [(b, a, s) for a, b, s in pairs]))
    return findings


def paragraphs(text: str) -> list[str]:
    """Split a review text into paragraphs at blank lines and list items, joining wrapped lines."""
    found = []
    for block in _BLOCK.split(text):
        lines: list[str] = []
        for line in block.splitlines():
            if _ITEM.match(line) and lines:
                found.append(" ".join(lines))
                lines = []
            if line.strip():
                lines.append(line.strip())
        if lines:
            found.append(" ".join(lines))
    return found


def _words(text: str) -> str:
    # Unlike dblp.fold, which keeps ASCII letters only, this keeps the words of every script.
    return " ".join(_WORD.findall(text.casefold()))


def _shingles(text: str, size: int) -> frozenset[str]:
    folded = _words(text)
    return frozenset(folded[i:i + size] for i in range(max(len(folded) - size + 1, 1)))


def _similar_pairs(items: list[_Paragraph], threshold: float, num_perm: int) -> list[tuple[int, int, float]]:
    # At the threshold itself, the index misses about half of the pairs at that similarity.
    lsh = MinHashLSH(threshold=threshold / 2, num_perm=num_perm)
    hashes = []
    for key, item in enumerate(items):
        minhash = MinHash(num_perm=num_perm)
        minhash.update_batch([shingle.encode("utf-8") for shingle in item.shingles])
        lsh.insert(key, minhash)
        hashes.append(minhash)
    pairs = []
    for key, minhash in enumerate(hashes):
        for other in sorted(lsh.query(minhash)):
            if other <= key or items[other].review == items[key].review:
                continue
            # LSH only proposes candidates, so the exact Jaccard similarity decides.
            a, b = items[key].shingles, items[other].shingles
            similarity = len(a & b) / len(a | b)
            if similarity >= threshold:
                pairs.append((key, other, similarity))
    return pairs


def _finding(review: Review, other: Review, pairs: list[tuple[int, int, float]]) -> Finding:
    where = []
    if other.paper_id is not None:
        where.append("on the same paper" if other.paper_id == review.paper_id else f"on paper {other.paper_id}")
    if review.reviewer and other.reviewer:
        where.append("by the same reviewer" if _same(review.reviewer, other.reviewer) else "by another reviewer")
    mine = len({number for number, _, _ in pairs})
    if mine == 1:
        lead = f"1 paragraph nearly duplicates text of review {other.review_id}"
    else:
        lead = f"{mine} paragraphs nearly duplicate text of review {other.review_id}"
    return Finding(
        check=CHECK,
        severity=Severity.WARNING,
        message=" ".join([lead, *where]),
        evidence="; ".join(
            f"paragraph {mine} here and paragraph {theirs} of review {other.review_id}, Jaccard {similarity:.2f}"
            for mine, theirs, similarity in sorted(pairs)
        ),
    )


def _same(a: Person, b: Person) -> bool:
    if a.email and b.email:
        return a.email.strip().lower() == b.email.strip().lower()
    # A name in a non-Latin script folds to nothing, therefore it counts as written.
    return (fold(a.name) or a.name.casefold()) == (fold(b.name) or b.name.casefold())

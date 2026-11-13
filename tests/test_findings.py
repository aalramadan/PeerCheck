"""Tests of the findings that every check reports and of the text that a finding shows as its evidence."""

from peercheck import findings
from peercheck.findings import Finding, Severity


def test_excerpt_puts_a_text_on_one_line():
    assert findings.excerpt("a  short\ntext\t of three   lines\n") == "a short text of three lines"


def test_excerpt_ends_a_long_text_with_an_ellipsis_at_the_limit():
    cut = findings.excerpt("word " * 60)
    assert len(cut) == findings.EVIDENCE_LIMIT
    assert cut.endswith("wo...")
    assert findings.excerpt("word " * 60, 20) == "word word word wo..."


def test_excerpt_leaves_no_blank_before_the_ellipsis():
    assert findings.excerpt("abcd " * 10, 13) == "abcd abcd..."


def test_finding_reads_as_one_line_with_its_page():
    finding = Finding("layout.pages", Severity.ERROR, "12 main pages", page=12)
    assert finding.as_text() == "ERROR layout.pages: 12 main pages (page 12)"
    assert Finding("layout.pages", Severity.INFO, "note").as_text() == "INFO layout.pages: note"


def test_a_paper_needs_review_once_a_finding_is_no_info_note():
    notes = [Finding("a.b", Severity.INFO, "note")]
    assert not findings.needs_review(notes)
    assert findings.needs_review([*notes, Finding("a.c", Severity.WARNING, "warning")])
    assert findings.count([*notes, Finding("a.c", Severity.WARNING, "warning")], Severity.INFO) == 1

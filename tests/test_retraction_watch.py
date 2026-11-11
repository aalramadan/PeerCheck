"""Tests of the Retraction Watch index, on a CSV of eight rows in the layout that Crossref publishes."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from peercheck.papers import retraction_watch
from peercheck.papers.retraction_watch import Notice

CSV = Path(__file__).parent / "fixtures" / "references" / "retraction_watch.csv"


def test_load_indexes_notices_by_the_doi_of_the_original_paper():
    index = retraction_watch.load(CSV)
    notices = index["10.1109/aswec.2008.4483193"]
    assert notices == (Notice(doi="10.1109/aswec.2008.4483193", nature="Retraction",
                              reason="Euphemisms for Plagiarism", date="2008-04-03"),)


def test_load_keeps_every_notice_of_a_paper_with_several():
    natures = [n.nature for n in retraction_watch.load(CSV)["10.9999/sample.2"]]
    assert natures == ["Retraction", "Reinstatement"]


def test_load_skips_rows_whose_original_paper_has_no_doi():
    index = retraction_watch.load(CSV)
    assert "unavailable" not in index
    assert len(index) == 5


def test_load_joins_the_reasons_of_a_notice():
    notice = retraction_watch.load(CSV)["10.9999/sample.3"][1]
    assert notice.reason == "Concerns/Issues About Results; Lack of Approval"
    assert notice.notice_doi == "10.9999/retraction.3"


def test_load_decodes_percent_encoded_dois():
    assert "10.1002/(sici)1097-4571(199806)49:8<693::aid-asi4>3.0.co;2-0" in retraction_watch.load(CSV)


def test_load_reads_a_changed_file_again(tmp_path):
    copy = tmp_path / "retraction_watch.csv"
    shutil.copyfile(CSV, copy)
    assert len(retraction_watch.load(copy)) == 5
    rows = copy.read_text(encoding="utf-8").splitlines()
    copy.write_text("\n".join(rows[:2]) + "\n", encoding="utf-8")
    os.utime(copy, ns=(1, 1))
    assert len(retraction_watch.load(copy)) == 1


def test_normalize_doi_removes_resolver_prefixes_and_case():
    assert retraction_watch.normalize_doi("https://doi.org/10.1109/ASWEC.2008.4483193.") == "10.1109/aswec.2008.4483193"
    assert retraction_watch.normalize_doi("doi: 10.1145/3180155.3180167") == "10.1145/3180155.3180167"
    assert retraction_watch.normalize_doi("https://dx.doi.org/10.1000/ABC") == "10.1000/abc"


def test_normalize_doi_rejects_text_without_a_doi():
    assert retraction_watch.normalize_doi("Unavailable") == ""
    assert retraction_watch.normalize_doi("10.1000") == ""


def test_match_returns_the_notices_of_cited_dois_only():
    index = retraction_watch.load(CSV)
    found = retraction_watch.match(["10.1145/3180155.3180167", "https://doi.org/10.1109/ASWEC.2008.4483193"], index)
    assert list(found) == ["10.1109/aswec.2008.4483193"]


def test_in_force_returns_a_retraction():
    notice = retraction_watch.in_force(retraction_watch.load(CSV)["10.1109/aswec.2008.4483193"])
    assert (notice.nature, notice.date) == ("Retraction", "2008-04-03")


def test_in_force_ignores_a_correction():
    assert retraction_watch.in_force(retraction_watch.load(CSV)["10.9999/sample.1"]) is None


def test_in_force_returns_none_after_a_later_reinstatement():
    assert retraction_watch.in_force(retraction_watch.load(CSV)["10.9999/sample.2"]) is None


def test_in_force_prefers_a_retraction_over_a_concern_of_the_same_date():
    assert retraction_watch.in_force(retraction_watch.load(CSV)["10.9999/sample.3"]).nature == "Retraction"


def test_in_force_returns_the_newest_notice():
    older = Notice(doi="10.1/a", nature="Retraction", reason="", date="2020-01-01")
    reinstated = Notice(doi="10.1/a", nature="Reinstatement", reason="", date="2021-01-01")
    retracted_again = Notice(doi="10.1/a", nature="Retraction", reason="", date="2022-01-01")
    assert retraction_watch.in_force([older, reinstated, retracted_again]) == retracted_again

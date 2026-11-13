"""Tests of the file that keeps the answers of the open indexes between runs."""

from __future__ import annotations

import json

import pytest

from peercheck.papers import lookup_cache
from peercheck.papers.lookup_cache import LookupCache
from peercheck.papers.open_indexes import Work

TITLE = "A made-up title on the porting of patches"
WORKS = [Work(TITLE, ("Ada Quill", "Ben Reed")), Work("Proceedings of a made-up meeting", (), container=True)]


class Index:
    """Stands in for an open index and counts the titles that it is asked for."""

    def __init__(self, works=()):
        self.works = list(works)
        self.asked: list[str] = []

    def __call__(self, title):
        self.asked.append(title)
        return self.works


def test_second_lookup_of_a_title_takes_the_records_of_the_first(tmp_path):
    kept, index = LookupCache(tmp_path / "kept.json"), Index(WORKS)
    assert kept.works("OpenAlex", TITLE, index) == WORKS
    assert kept.works("OpenAlex", TITLE, index) == WORKS
    assert index.asked == [TITLE]


def test_each_source_keeps_its_own_records_of_a_title(tmp_path):
    kept, index = LookupCache(tmp_path / "kept.json"), Index()
    kept.works("OpenAlex", TITLE, Index(WORKS))
    assert kept.works("DataCite", TITLE, index) == []
    assert index.asked == [TITLE]


def test_saved_records_answer_a_lookup_of_a_later_run(tmp_path):
    first = LookupCache(tmp_path / "kept.json")
    first.works("OpenAlex", TITLE, Index(WORKS))
    first.works("OpenAlex", "A title that no index holds", Index())
    first.save()
    later, index = LookupCache(tmp_path / "kept.json"), Index()
    assert later.works("OpenAlex", TITLE, index) == WORKS
    assert later.works("OpenAlex", "A title that no index holds", index) == []
    assert index.asked == []


@pytest.mark.parametrize(("works", "days", "asked_again"), [
    (WORKS, 6.9, False), (WORKS, 7.1, True), ([], 0.9, False), ([], 1.1, True)])
def test_title_with_records_is_kept_for_seven_days_and_a_title_without_one_for_a_day(tmp_path, monkeypatch, works,
                                                                                     days, asked_again):
    first = LookupCache(tmp_path / "kept.json")
    first.works("OpenAlex", TITLE, Index(works))
    first.save()
    now = lookup_cache.time.time()
    monkeypatch.setattr(lookup_cache.time, "time", lambda: now + days * lookup_cache.DAY)
    index = Index(works)
    LookupCache(tmp_path / "kept.json").works("OpenAlex", TITLE, index)
    assert index.asked == [TITLE] * asked_again


def test_answer_that_a_later_run_saves_again_still_ages_from_its_first_lookup(tmp_path, monkeypatch):
    first = LookupCache(tmp_path / "kept.json")
    first.works("OpenAlex", TITLE, Index(WORKS))
    first.save()
    now = lookup_cache.time.time()
    monkeypatch.setattr(lookup_cache.time, "time", lambda: now + 6 * lookup_cache.DAY)
    LookupCache(tmp_path / "kept.json").save()
    monkeypatch.setattr(lookup_cache.time, "time", lambda: now + 7.1 * lookup_cache.DAY)
    index = Index(WORKS)
    LookupCache(tmp_path / "kept.json").works("OpenAlex", TITLE, index)
    assert index.asked == [TITLE]


def test_lookup_that_fails_passes_its_error_on_and_keeps_no_answer(tmp_path):
    kept, index = LookupCache(tmp_path / "kept.json"), Index(WORKS)

    def down(title):
        raise OSError("made-up outage")

    with pytest.raises(OSError, match="made-up outage"):
        kept.works("OpenAlex", TITLE, down)
    assert kept.works("OpenAlex", TITLE, index) == WORKS
    assert index.asked == [TITLE]


@pytest.mark.parametrize("content", ["no JSON", "[1, 2]", '{"OpenAlex\\nA title": 3}', '{"OpenAlex\\nA title": [1]}',
                                     '{"OpenAlex\\nA title": ["then", [["A title"]]]}'])
def test_file_that_is_no_json_or_has_another_form_starts_an_empty_cache(tmp_path, content):
    (tmp_path / "kept.json").write_text(content, encoding="utf-8")
    kept, index = LookupCache(tmp_path / "kept.json"), Index(WORKS)
    assert kept.works("OpenAlex", "A title", index) == WORKS
    assert index.asked == ["A title"]


def test_save_writes_each_answer_with_its_time_and_leaves_no_partial_file(tmp_path, monkeypatch):
    monkeypatch.setattr(lookup_cache.time, "time", lambda: 1000.0)
    kept = LookupCache(tmp_path / "kept.json")
    kept.works("OpenAlex", TITLE, Index(WORKS))
    kept.save()
    assert json.loads((tmp_path / "kept.json").read_text(encoding="utf-8")) == {f"OpenAlex\n{TITLE}": [1000.0, [
        [TITLE, ["Ada Quill", "Ben Reed"], False], ["Proceedings of a made-up meeting", [], True]]]}
    assert [path.name for path in tmp_path.iterdir()] == ["kept.json"]


def test_file_that_cannot_be_written_leaves_the_run_going(tmp_path):
    kept = LookupCache(tmp_path / "no-folder" / "kept.json")
    kept.works("OpenAlex", TITLE, Index(WORKS))
    kept.save()
    assert not (tmp_path / "no-folder").exists()


def test_file_that_cannot_take_the_place_of_the_old_one_leaves_no_partial_file(tmp_path):
    (tmp_path / "kept.json").mkdir()
    kept = LookupCache(tmp_path / "kept.json")
    kept.works("OpenAlex", TITLE, Index(WORKS))
    kept.save()
    assert [path.name for path in tmp_path.iterdir()] == ["kept.json"]

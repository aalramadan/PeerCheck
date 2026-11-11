"""Tests of the clean-up of untagged images in the Docker workflow, offline."""

import importlib.util
import io
import urllib.error
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / ".github" / "scripts" / "prune_images.py"
SPEC = importlib.util.spec_from_file_location("prune_images", SCRIPT)
prune = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(prune)


def _version(number, name, tags=()):
    return {"id": number, "name": name, "metadata": {"container": {"tags": list(tags)}}}


def _registry(versions):
    """Answer the GET requests of the script for one page of versions, no tags, and single images."""
    def fetch(url, headers):
        if "/versions" in url:
            return versions
        if "/tags" in url:
            return []
        return {"token": "anonymous"} if "/token" in url else {"config": {}, "layers": []}
    return fetch


def _run_offline(monkeypatch, fetch, urlopen):
    monkeypatch.setattr(prune, "fetch", fetch)
    monkeypatch.setattr(prune.urllib.request, "urlopen", urlopen)
    monkeypatch.setenv("GITHUB_REPOSITORY_OWNER", "example")
    monkeypatch.setenv("GITHUB_REPOSITORY", "example/PeerCheck")
    monkeypatch.setenv("GITHUB_TOKEN", "offline")
    prune.main()


def test_untagged_versions_go_and_tagged_ones_stay():
    versions = [_version(1, "sha256:new", ["latest"]), _version(2, "sha256:old"), _version(3, "sha256:older")]
    assert [v["id"] for v in prune.to_delete(versions, set())] == [2, 3]


def test_child_manifests_of_a_tagged_index_stay():
    versions = [_version(1, "sha256:index", ["1.0.0"]), _version(2, "sha256:amd64"), _version(3, "sha256:attestation"),
                _version(4, "sha256:old")]
    needed = prune.listed_digests({"manifests": [{"digest": "sha256:amd64"}, {"digest": "sha256:attestation"}]})
    assert [v["id"] for v in prune.to_delete(versions, needed)] == [4]


def test_a_single_image_lists_no_child_manifests():
    assert prune.listed_digests({"config": {}, "layers": []}) == set()


def test_images_of_a_removed_release_go_and_latest_stays():
    versions = [_version(1, "sha256:new", ["latest"]), _version(2, "sha256:kept", ["1.0.0"]),
                _version(3, "sha256:removed", ["1.1.0"]), _version(4, "sha256:shared", ["latest", "1.1.0"])]
    assert [v["id"] for v in prune.stale_releases(versions, {"1.0.0"})] == [3]


def test_image_of_a_release_whose_tag_is_on_the_second_page_of_tags_stays(monkeypatch):
    tags = [{"name": f"v1.0.{number}"} for number in range(100, -1, -1)]
    versions = [_version(1, "sha256:new", ["latest", "1.0.100"]), _version(2, "sha256:first", ["1.0.0"])]

    def fetch(url, headers):
        page = int(parse_qs(urlsplit(url).query).get("page", ["1"])[0])
        if "/tags" in url:
            return tags[(page - 1) * 100:page * 100]
        if "/versions" in url:
            return versions if page == 1 else []
        return {"token": "anonymous"} if "/token" in url else {"config": {}, "layers": []}

    deleted = []

    def delete(request):
        deleted.append(request.full_url)
        return io.BytesIO()

    _run_offline(monkeypatch, fetch, delete)
    assert deleted == []


def test_a_version_that_a_parallel_run_deleted_first_is_skipped(monkeypatch, capsys):
    versions = [_version(1, "sha256:new", ["latest"]), _version(2, "sha256:gone"), _version(3, "sha256:old")]

    def delete(request):
        if request.full_url.endswith("/2"):
            raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, None)
        return io.BytesIO()

    _run_offline(monkeypatch, _registry(versions), delete)
    assert capsys.readouterr().out == "deleted sha256:old\n"


def test_a_refused_deletion_still_fails(monkeypatch):
    versions = [_version(1, "sha256:new", ["latest"]), _version(2, "sha256:old")]

    def refuse(request):
        raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", {}, None)

    with pytest.raises(urllib.error.HTTPError):
        _run_offline(monkeypatch, _registry(versions), refuse)

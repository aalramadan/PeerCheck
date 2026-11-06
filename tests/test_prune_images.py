"""Tests of the clean-up of untagged images in the Docker workflow, offline."""

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / ".github" / "scripts" / "prune_images.py"
SPEC = importlib.util.spec_from_file_location("prune_images", SCRIPT)
prune = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(prune)


def _version(number, name, tags=()):
    return {"id": number, "name": name, "metadata": {"container": {"tags": list(tags)}}}


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

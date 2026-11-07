"""Deletes the images of PeerCheck on GitHub that lost their tag or whose release was removed.

A tagged image built for several platforms lists child manifests without tags, which stay with it."""

import json
import os
import re
import urllib.request

INDEX_TYPES = ("application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json, "
               "application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json")


def to_delete(versions: list[dict], needed: set[str]) -> list[dict]:
    """Return the versions without a tag whose digest no tagged image lists."""
    return [v for v in versions if not v["metadata"]["container"]["tags"] and v["name"] not in needed]


def stale_releases(versions: list[dict], releases: set[str]) -> list[dict]:
    """Return the versions whose every tag names a release that no longer exists, such as 1.1.0."""
    version_tag = re.compile(r"^\d+\.\d+\.\d+$")
    return [v for v in versions if v["metadata"]["container"]["tags"]
            and all(version_tag.match(tag) and tag not in releases for tag in v["metadata"]["container"]["tags"])]


def listed_digests(manifest: dict) -> set[str]:
    """Return the digests of the child manifests that an image index lists, or none for a single image."""
    return {entry["digest"] for entry in manifest.get("manifests", [])}


def fetch(url: str, headers: dict[str, str]) -> object:
    """Return the JSON answer of a GET request."""
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers)) as reply:
        return json.load(reply)


def fetch_all(url: str, headers: dict[str, str]) -> list:
    """Return every item of a list of the GitHub API, which gives at most 100 items per page."""
    items, page = [], 1
    while True:
        batch = fetch(f"{url}?per_page=100&page={page}", headers)
        items += batch
        if len(batch) < 100:
            return items
        page += 1


def main() -> None:
    """Delete every untagged version that no tagged image needs and print each deleted digest."""
    owner, package = os.environ["GITHUB_REPOSITORY_OWNER"].lower(), "peercheck"
    api = f"https://api.github.com/users/{owner}/packages/container/{package}/versions"
    github = {"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}", "Accept": "application/vnd.github+json"}
    versions = fetch_all(api, github)
    tags = fetch_all(f"https://api.github.com/repos/{os.environ['GITHUB_REPOSITORY']}/tags", github)
    stale = stale_releases(versions, {tag["name"].removeprefix("v") for tag in tags})
    pull = fetch(f"https://ghcr.io/token?scope=repository:{owner}/{package}:pull", {})["token"]
    registry = {"Authorization": f"Bearer {pull}", "Accept": INDEX_TYPES}
    needed = set()
    for version in versions:
        if version in stale:
            continue
        for tag in version["metadata"]["container"]["tags"]:
            needed |= listed_digests(fetch(f"https://ghcr.io/v2/{owner}/{package}/manifests/{tag}", registry))
    for version in stale + to_delete(versions, needed):
        urllib.request.urlopen(urllib.request.Request(f"{api}/{version['id']}", method="DELETE", headers=github)).close()
        print(f"deleted {version['name']}")


if __name__ == "__main__":
    main()

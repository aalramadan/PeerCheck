"""Deletes the versions of the PeerCheck image on GitHub that carry no tag and that no tagged image lists.

Each push moves the tag latest to a new image, and the image before it stays behind without a tag. The Docker
workflow runs this script after each push with the token of the workflow. A tagged image built for several
platforms lists child manifests without tags, and these stay, since the tagged image needs them.
"""

import json
import os
import urllib.request

INDEX_TYPES = ("application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json, "
               "application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json")


def to_delete(versions: list[dict], needed: set[str]) -> list[dict]:
    """Return the versions without a tag whose digest no tagged image lists."""
    return [v for v in versions if not v["metadata"]["container"]["tags"] and v["name"] not in needed]


def listed_digests(manifest: dict) -> set[str]:
    """Return the digests of the child manifests that an image index lists, or none for a single image."""
    return {entry["digest"] for entry in manifest.get("manifests", [])}


def fetch(url: str, headers: dict[str, str]) -> object:
    """Return the JSON answer of a GET request."""
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers)) as reply:
        return json.load(reply)


def main() -> None:
    """Delete every untagged version that no tagged image needs and print each deleted digest."""
    owner, package = os.environ["GITHUB_REPOSITORY_OWNER"].lower(), "peercheck"
    api = f"https://api.github.com/users/{owner}/packages/container/{package}/versions"
    github = {"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}", "Accept": "application/vnd.github+json"}
    versions, page = [], 1
    while True:
        batch = fetch(f"{api}?per_page=100&page={page}", github)
        versions += batch
        if len(batch) < 100:
            break
        page += 1
    pull = fetch(f"https://ghcr.io/token?scope=repository:{owner}/{package}:pull", {})["token"]
    registry = {"Authorization": f"Bearer {pull}", "Accept": INDEX_TYPES}
    needed = set()
    for version in versions:
        for tag in version["metadata"]["container"]["tags"]:
            needed |= listed_digests(fetch(f"https://ghcr.io/v2/{owner}/{package}/manifests/{tag}", registry))
    for version in to_delete(versions, needed):
        urllib.request.urlopen(urllib.request.Request(f"{api}/{version['id']}", method="DELETE", headers=github)).close()
        print(f"deleted {version['name']}")


if __name__ == "__main__":
    main()

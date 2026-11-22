"""Wait for exact Release-tag push CI before taking the production lease."""

from __future__ import annotations

import base64
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.release_content import parse_version_source  # noqa: E402
from scripts.static_ops import source_ci  # noqa: E402

TAG = re.compile(r"v(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)")
SHA = re.compile(r"[0-9a-f]{40}")
PUBLISHER = ".github/workflows/publish-github-release.yml"
BRANCHES = {"main", "release/1.x", "release/2.x"}


def release_tag(get, name: str, event: dict) -> str:
    """Select only a stable tag; the publisher revalidates its complete identity."""
    if event.get("repository", {}).get("full_name") != source_ci.REPO:
        raise source_ci.Unavailable("Unexpected release event repository")
    if name == "release":
        if event.get("action") != "published":
            raise source_ci.Unavailable("Expected a published Release")
        release = event["release"]
        if release.get("draft") is not False or release.get("prerelease") is not False:
            raise source_ci.Unavailable("Expected a stable published Release")
        tag = release["tag_name"]
    elif name == "workflow_run":
        run = event["workflow_run"]
        if not (event.get("action") == "completed"
                and run.get("event") == "push" and run.get("conclusion") == "success"
                and run.get("path") == PUBLISHER
                and run.get("head_branch") in BRANCHES
                and run.get("head_repository", {}).get("full_name") == source_ci.REPO
                and isinstance(run.get("head_sha"), str)
                and SHA.fullmatch(run["head_sha"])):
            raise source_ci.Unavailable("Expected successful Release publisher push")
        value = get("contents/VERSION?ref=" + run["head_sha"])
        if value.get("type") != "file" or value.get("encoding") != "base64":
            raise source_ci.Unavailable("Invalid publisher VERSION content")
        try:
            contents = base64.b64decode(value["content"], validate=False).decode("utf-8")
            tag = "v" + parse_version_source(contents)
        except (KeyError, ValueError, UnicodeError):
            raise source_ci.Unavailable("Invalid publisher VERSION content") from None
    else:
        raise source_ci.Unavailable("Unsupported release trigger")
    if not isinstance(tag, str) or not TAG.fullmatch(tag):
        raise source_ci.Unavailable("A stable Release version is required")
    return tag


def release_commit(get, tag: str) -> str:
    """Resolve annotated tags to the commit evaluated by source CI."""
    obj = get("git/ref/tags/" + tag)["object"]
    for _ in range(16):
        if not isinstance(obj.get("sha"), str) or not SHA.fullmatch(obj["sha"]):
            break
        if obj.get("type") == "commit":
            return obj["sha"]
        if obj.get("type") != "tag":
            break
        obj = get("git/tags/" + obj["sha"])["object"]
    raise source_ci.Unavailable("Release tag is not a valid commit")


def await_source_ci(get, sha: str, *, timeout: float = 2400, interval: float = 15,
                    monotonic=time.monotonic, sleep=time.sleep) -> dict:
    deadline = monotonic() + timeout
    while True:
        try:
            return source_ci.require_success(get, sha)
        except source_ci.Unavailable:
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise source_ci.Unavailable("Release source CI did not pass before timeout") from None
            sleep(min(interval, remaining))


def main() -> None:
    get = source_ci.GitHub(os.environ["GH_TOKEN"])
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    tag = release_tag(get, os.environ["GITHUB_EVENT_NAME"], event)
    sha = release_commit(get, tag)
    receipt = await_source_ci(get, sha)
    print(f"Release {tag}: source CI run {receipt['run_id']} attempt {receipt['run_attempt']} passed")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        raise SystemExit("Release source CI preflight BLOCKED: inspect the source CI and replay") from None

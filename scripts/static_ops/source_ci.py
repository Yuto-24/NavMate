"""Read existing GitHub Actions evidence; never wait or change remote state.

Promotion requires a completed full push run for the application SHA. Optional
Web inventory only authorizes reuse after the build environment also matches.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

REPO = "Yuto-24/NavMate"
WORKFLOW = ".github/workflows/test.yml"
INVENTORY_SCRIPT = "web/scripts/source-ci-inventory.mjs"
REQUIRED = {"release-sources", "pytest", "web", "local-browser", "account-sync", "ci-required"}
WEB_STEPS = {"Run npm --prefix web ci", "Run npm --prefix web run typecheck",
             "Run npm --prefix web run test:static-artifact"}
LIMIT = 2 * 1024 * 1024


class Unavailable(ValueError):
    """No usable source validation; retain the current application."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class GitHub:
    def __init__(self, token: str = ""):
        self.token = token

    def request(self, endpoint: str) -> Request:
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "NavMate-source-ci",
                   "X-GitHub-Api-Version": "2022-11-28"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        return Request(f"https://api.github.com/repos/{REPO}/{endpoint}", headers=headers)

    @staticmethod
    def read(response) -> bytes:
        data = response.read(LIMIT + 1)
        if len(data) > LIMIT:
            raise Unavailable("Source CI response exceeds bound")
        return data

    def __call__(self, endpoint: str):
        # Do not redirect authenticated API reads to a different repository/host.
        with build_opener(NoRedirect).open(self.request(endpoint), timeout=15) as response:
            return json.loads(self.read(response))

    def download(self, artifact_id: int) -> bytes:
        try:
            with build_opener(NoRedirect).open(
                self.request(f"actions/artifacts/{artifact_id}/zip"), timeout=15
            ) as response:
                return self.read(response)
        except HTTPError as error:
            if error.code != 302:
                raise
            location = error.headers.get("Location", "")
        url = urlsplit(location)
        if (url.scheme != "https" or url.username or url.password
                or not (url.hostname or "").endswith(".blob.core.windows.net")):
            raise Unavailable("Unexpected source CI artifact location")
        # The signed download receives no GitHub Authorization header.
        with build_opener(NoRedirect).open(location, timeout=15) as response:
            return self.read(response)


def successful(value: dict) -> bool:
    return value.get("status") == "completed" and value.get("conclusion") == "success"


def require_success(get, sha: str) -> dict:
    """Use the latest push attempt, never a PR merge SHA or older successful retry."""
    try:
        if not re.fullmatch(r"[a-f0-9]{40}", sha):
            raise Unavailable("Invalid application SHA")
        runs = get(f"actions/workflows/test.yml/runs?head_sha={sha}&event=push&per_page=100")
        candidates = [run for run in runs["workflow_runs"] if run.get("head_sha") == sha
                      and run.get("event") == "push"]
        if not candidates:
            raise Unavailable("Source CI push run missing")
        run = max(candidates, key=lambda item: item["id"])
        if (not successful(run) or run.get("path") != WORKFLOW
                or run.get("head_repository", {}).get("full_name") != REPO
                or run.get("head_branch") not in ("main", "release/1.x", "release/2.x")
                or type(run.get("id")) is not int or run["id"] < 1
                or type(run.get("run_attempt")) is not int or run["run_attempt"] < 1):
            raise Unavailable("Source CI is not a successful trusted push run")
        jobs = []
        for page in range(1, 5):
            batch = get(f"actions/runs/{run['id']}/attempts/{run['run_attempt']}/jobs"
                        f"?per_page=100&page={page}")
            jobs.extend(batch["jobs"])
            if len(jobs) == batch["total_count"]:
                break
        else:
            raise Unavailable("Source CI job inventory incomplete")
        for name in REQUIRED:
            selected = [job for job in jobs if job.get("name") == name]
            if len(selected) != 1 or not successful(selected[0]):
                raise Unavailable("Required source CI suite missing or unsuccessful: " + name)
        web = next(job for job in jobs if job["name"] == "web")
        completed = {step["name"] for step in web["steps"] if successful(step)}
        if not WEB_STEPS <= completed:
            raise Unavailable("Source CI Web checks were not executed")
        return {"sha": sha, "run_id": run["id"], "run_attempt": run["run_attempt"]}
    except Unavailable:
        raise
    except Exception:
        # Never log signed URLs, tokens, HTTP bodies or provider error text.
        raise Unavailable("Source CI evidence unavailable") from None


def web_inventory(get, download, receipt: dict, tooling: Path) -> dict | None:
    """Missing/expired/unmatched inventory means rerun checks, never bypass them."""
    try:
        data = get(f"actions/runs/{receipt['run_id']}/artifacts?per_page=100")
        if len(data["artifacts"]) != data["total_count"]:
            return None
        name = f"source-ci-web-{receipt['run_attempt']}"
        artifacts = [a for a in data["artifacts"] if a["name"] == name]
        if len(artifacts) != 1 or artifacts[0].get("expired") is not False:
            return None
        artifact = artifacts[0]
        if artifact["workflow_run"]["head_sha"] != receipt["sha"]:
            return None
        raw = download(artifact["id"])
        if len(raw) > LIMIT or "sha256:" + hashlib.sha256(raw).hexdigest() != artifact["digest"]:
            return None
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            if archive.namelist() != ["source-ci-web.json"]:
                return None
            if archive.infolist()[0].file_size > 65536:
                return None
            value = json.loads(archive.read("source-ci-web.json"))
        if (value["sha"] != receipt["sha"] or value["run_id"] != str(receipt["run_id"])
                or value["run_attempt"] != str(receipt["run_attempt"])
                or value["workflow"] != hashlib.sha256(
                    (tooling / WORKFLOW).read_bytes()).hexdigest()
                or value["producer"] != hashlib.sha256(
                    (tooling / INVENTORY_SCRIPT).read_bytes()).hexdigest()):
            return None
        return value
    except Exception:
        return None

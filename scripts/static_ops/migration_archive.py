"""Reuse the bounded encrypted migration transport with per-operation identities."""

from __future__ import annotations

import io
import json
import subprocess
import zipfile
from pathlib import Path, PurePosixPath

from scripts.static_ops import app_release as app
from scripts.static_ops import schema260_bundle as transport


def restore(archive: Path, key: bytes, destination: Path, evidence: Path, approved: dict):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    raw = transport.read_file(archive, transport.MAX_ARCHIVE)
    app.require(app.digest(raw) == approved["archive_sha256"], "Prepared archive changed")
    magic = transport.MAGIC
    app.require(raw.startswith(magic) and len(raw) > len(magic) + 28, "Invalid encrypted archive")
    start = len(magic)
    plain = AESGCM(key).decrypt(raw[start : start + 12], raw[start + 12 :], magic)
    files, total = {}, 0
    with zipfile.ZipFile(io.BytesIO(plain)) as zipped:
        app.require(0 < len(zipped.infolist()) <= transport.MAX_FILES, "Archive file limit")
        for member in zipped.infolist():
            name, path = member.filename, PurePosixPath(member.filename)
            total += member.file_size
            app.require(
                not member.is_dir()
                and not path.is_absolute()
                and ".." not in path.parts
                and str(path) == name
                and "\\" not in name
                and name not in files
                and total <= transport.MAX_PAYLOAD,
                "Archive path or capacity",
            )
            app.require(
                name
                in (
                    "store/plan.json",
                    "store/prepare-status.json",
                    "store/handoff.json",
                    "store/prepared/feed-report.json",
                    "evidence/SCHEMA_RECORD.json",
                    "evidence/old_to_new.json",
                    "evidence/old_writer_fenced.json",
                    "evidence/storage_sync_roundtrip.json",
                )
                or name.startswith("store/prepared/upload/"),
                "Unexpected archive file",
            )
            files[name] = zipped.read(member)
    plan = files["store/plan.json"]
    app.require(
        app.digest(plan) == approved["plan_sha256"] and json.loads(plan) == approved["plan"],
        "Reviewed plan mismatch",
    )
    handoff = json.loads(files["store/handoff.json"])
    app.require(handoff == approved["handoff"], "Prepared handoff mismatch")
    app.require(not destination.exists() and not evidence.exists(), "Fresh restore required")
    destination.mkdir(mode=0o700)
    evidence.mkdir(mode=0o700)
    for name, content in files.items():
        prefix, relative = name.split("/", 1)
        transport.write_private(
            (destination if prefix == "store" else evidence) / relative, content
        )


def completed_run(operator, identity, tooling_sha, job_name, events):
    run_id, attempt = identity["run_id"], identity["run_attempt"]
    app.require(
        all(isinstance(v, str) and v.isdecimal() and int(v) > 0 for v in (run_id, attempt)),
        "Invalid prepare run identity",
    )
    run = operator.gh("actions/runs/" + run_id)
    app.require(
        run.get("id") == int(run_id)
        and run.get("run_attempt") == int(attempt)
        and run.get("status") == "completed"
        and run.get("conclusion") == "success"
        and run.get("event") in events
        and run.get("head_branch") == "main"
        and run.get("path") == ".github/workflows/static-app-release.yml"
        and run.get("head_sha") == tooling_sha
        and run.get("repository", {}).get("id") == 1314030412
        and run.get("head_repository", {}).get("id") == 1314030412,
        "Successful exact prepare attempt required",
    )
    workflow = operator.gh("actions/workflows/static-app-release.yml")
    app.require(
        workflow.get("path") == ".github/workflows/static-app-release.yml"
        and workflow.get("state") == "active"
        and type(workflow.get("id")) is int
        and workflow["id"] > 0
        and run.get("workflow_id") == workflow["id"],
        "Publication workflow identity changed",
    )
    # A successful unrelated/skipped job cannot stand in for prepare.
    jobs, page, total = [], 1, None
    while True:
        response = operator.gh(
            f"actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100&page={page}"
        )
        count, rows = response["total_count"], response["jobs"]
        app.require(
            type(count) is int
            and count > 0
            and isinstance(rows, list)
            and (total is None or total == count),
            "Prepare job inventory changed",
        )
        total = count
        jobs.extend(rows)
        app.require(
            len({job["id"] for job in jobs}) == len(jobs) <= total,
            "Incomplete or duplicate prepare jobs",
        )
        if len(jobs) == total:
            break
        app.require(len(rows) == 100, "Incomplete prepare jobs")
        page += 1
        app.require(page <= 4, "Prepare job inventory limit exceeded")
    matches = [job for job in jobs if job.get("name") == job_name]
    app.require(
        len(matches) == 1
        and matches[0].get("conclusion") == "success"
        and matches[0].get("status") == "completed",
        "Prepare job did not complete",
    )
    return run


def source_run(operator, approved):
    return completed_run(
        operator,
        approved["handoff"]["origin_run"],
        approved["plan"]["snapshot"]["tooling_sha"],
        "migration-prepare",
        {"workflow_dispatch"},
    )


def evidence_run(operator, evidence):
    return completed_run(
        operator,
        evidence["origin_run"],
        evidence["identity"]["tooling_sha"],
        "migration-evidence",
        {"workflow_dispatch", "workflow_run"},
    )


def download(operator, approved, directory):
    run = source_run(operator, approved)
    origin = approved["handoff"]["origin_run"]
    suffix = origin["run_id"] + "-" + origin["run_attempt"]
    name = "migration-" + suffix
    result = operator.gh(
        f"actions/runs/{origin['run_id']}/artifacts?name={name}&per_page=100&page=1"
    )
    app.require(
        type(result["total_count"]) is int
        and result["total_count"] == 1
        and len(result["artifacts"]) == 1,
        "Unique prepared archive required",
    )
    artifact = result["artifacts"][0]
    identity = artifact.get("workflow_run", {})
    app.require(
        type(artifact.get("id")) is int
        and artifact["id"] > 0
        and artifact.get("expired") is False
        and artifact.get("name") == name
        and type(artifact.get("size_in_bytes")) is int
        and 0 < artifact["size_in_bytes"] <= transport.MAX_ARCHIVE + 65536
        and identity.get("id") == run["id"]
        and identity.get("repository_id") == 1314030412
        and identity.get("head_repository_id") == 1314030412
        and identity.get("head_sha") == run["head_sha"],
        "Invalid prepared archive identity",
    )
    target = directory / "download.zip"
    with target.open("xb") as output:
        subprocess.run(
            [
                "gh",
                "api",
                "--hostname",
                "github.com",
                "--method",
                "GET",
                f"repos/{app.REPO}/actions/artifacts/{artifact['id']}/zip",
            ],
            env={
                **{
                    key: operator.env[key]
                    for key in ("PATH", "HOME", "GH_TOKEN")
                    if key in operator.env
                },
                "GH_PROMPT_DISABLED": "1",
            },
            stdout=output,
            stderr=subprocess.PIPE,
            check=True,
            timeout=180,
        )
    app.require(
        target.stat().st_size <= transport.MAX_ARCHIVE + 65536, "Archive download too large"
    )
    with zipfile.ZipFile(target) as zipped:
        members = zipped.infolist()
        app.require(
            len(members) == 1
            and members[0].filename == "migration-result-" + suffix + ".aesgcm"
            and 0 < members[0].file_size <= transport.MAX_ARCHIVE,
            "Invalid archive member",
        )
        raw = zipped.read(members[0])
    app.require(app.digest(raw) == approved["archive_sha256"], "Prepared artifact digest changed")
    result = directory / "prepared.aesgcm"
    transport.write_private(result, raw)
    app.require(source_run(operator, approved) == run, "Prepare attempt changed during download")
    return result

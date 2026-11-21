"""Bounded advisory timings. No command, output, exception or provider data is retained."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

PHASES = frozenset(
    {
        "preflight",
        "build-test",
        "pause",
        "paused-readback",
        "quiescence",
        "fresh-build-test",
        "pre-upload",
        "upload",
        "canonical-verification",
        "approved-sha",
        "resume",
        "archive",
        "msm-restore",
        "msm-acquisition",
        "container-image",
        "dependencies-python",
        "dependencies-node",
        "dependencies-browser",
        "source-validation",
        "source-ci",
        "source-typecheck-reused",
        "source-artifact-tests-reused",
        "static-build",
        "artifact-tests",
        "e2e",
        "canonical-after-approval",
        "upload-dependencies",
        "encrypted-save",
        "artifact-download",
        "artifact-decrypt",
        "workflow-dependencies",
        "artifact-upload",
        "review-upload",
    }
)
STATES = {"RUNNING", "OK", "BLOCKED", "INTERRUPTED", "SKIPPED"}


def stamp() -> str:
    return datetime.now(UTC).isoformat()


def write(path: Path, value: object) -> None:
    temporary = path.with_suffix(".tmp")
    with temporary.open("w") as stream:
        os.chmod(temporary, 0o600)
        json.dump(value, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def bounded(rows: object) -> list[dict]:
    """Project untrusted container/private records onto a strict public schema."""
    if not isinstance(rows, list) or len(rows) > 100:
        raise ValueError("Invalid timing records")
    result = []
    for row in rows:
        if (
            not isinstance(row, dict)
            or row.get("phase") not in PHASES
            or row.get("status") not in STATES
        ):
            raise ValueError("Invalid timing record")
        clean = {"phase": row["phase"], "status": row["status"]}
        for key in ("started_at", "finished_at"):
            value = row.get(key)
            if value is not None:
                parsed = datetime.fromisoformat(value)
                if parsed.tzinfo is None:
                    raise ValueError("Invalid timing timestamp")
                clean[key] = parsed.astimezone(UTC).isoformat()
        duration = row.get("seconds")
        if duration is not None:
            if type(duration) not in (int, float) or not math.isfinite(duration) or duration < 0:
                raise ValueError("Invalid timing duration")
            clean["seconds"] = round(duration, 3)
        result.append(clean)
    return result


@contextmanager
def measure(rows: list, save, phase: str):
    if phase not in PHASES:
        raise ValueError("Invalid timing phase")
    row = {"phase": phase, "status": "RUNNING", "started_at": stamp()}
    rows.append(row)
    save()  # A kill leaves RUNNING, never a fabricated successful interval.
    start = time.monotonic()
    try:
        yield
    except BaseException as error:
        row["status"] = (
            "INTERRUPTED" if isinstance(error, (KeyboardInterrupt, SystemExit)) else "BLOCKED"
        )
        raise
    else:
        row["status"] = "OK"
    finally:
        row.update(finished_at=stamp(), seconds=round(time.monotonic() - start, 3))
        save()


# Exact workflow step names only; arbitrary names/responses must never be printed.
WORKFLOW_PHASES = {
    "Install the fixed reviewed tooling dependencies": "workflow-dependencies",
    "Install trusted producer tooling": "workflow-dependencies",
    "Retain only the authenticated encrypted result": "artifact-upload",
    "Retain only the authenticated encrypted publication record": "artifact-upload",
    "Retain the small preparation observation first": "review-upload",
    "Retain the small publication observation first": "review-upload",
    "Retain bounded common release observations": "review-upload",
}


def workflow_rows(payload: dict, run_id: str, job_name: str) -> list[dict]:
    jobs = payload["jobs"]
    if payload["total_count"] != len(jobs) or len(jobs) > 100:
        raise ValueError("Incomplete jobs inventory")
    matching = [job for job in jobs if job.get("name") == job_name]
    if len(matching) != 1 or matching[0].get("run_id") != int(run_id):
        raise ValueError("Workflow job identity mismatch")
    rows = []
    for step in matching[0]["steps"]:
        phase = WORKFLOW_PHASES.get(step.get("name"))
        if phase is None:
            continue
        status = "RUNNING"
        if step.get("status") == "completed":
            status = {"success": "OK", "cancelled": "INTERRUPTED", "skipped": "SKIPPED"}.get(
                step.get("conclusion"), "BLOCKED"
            )
        row = {"phase": phase, "status": status}
        if step.get("started_at") and step.get("completed_at"):
            start = datetime.fromisoformat(step["started_at"])
            end = datetime.fromisoformat(step["completed_at"])
            row.update(
                started_at=start.isoformat(),
                finished_at=end.isoformat(),
                seconds=(end - start).total_seconds(),
            )
        rows.append(row)
    return bounded(rows)


def workflow_report(env: dict) -> dict:
    """One GET snapshot after upload; unavailable intervals are never zero/success."""
    try:
        run, attempt = env["GITHUB_RUN_ID"], env["GITHUB_RUN_ATTEMPT"]
        if not all(re.fullmatch(r"[1-9]\d{0,19}", v) for v in (run, attempt)):
            raise ValueError("Invalid workflow identity")
        if env["GITHUB_JOB"] not in {"publish", "manual-prepare", "manual-publish"}:
            raise ValueError("Invalid workflow job")
        result = subprocess.run(
            [
                "gh",
                "api",
                "--hostname",
                "github.com",
                "--method",
                "GET",
                f"repos/Yuto-24/NavMate/actions/runs/{run}/attempts/{attempt}/jobs?per_page=100",
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
            env={key: env[key] for key in ("PATH", "HOME", "GH_TOKEN") if key in env},
        )
        if len(result.stdout) > 1024 * 1024:
            raise ValueError("Workflow response too large")
        return {
            "status": "OBSERVED",
            "run_id": run,
            "run_attempt": attempt,
            "timings": workflow_rows(json.loads(result.stdout), run, env["GITHUB_JOB"]),
        }
    except Exception:
        return {"status": "UNAVAILABLE", "timings": []}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--phase", choices=sorted(PHASES), required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    rows = json.loads(args.file.read_text()) if args.file.exists() else []
    bounded(rows)
    try:
        with measure(rows, lambda: write(args.file, rows), args.phase):
            subprocess.run(args.command, check=True)
    except (Exception, KeyboardInterrupt):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

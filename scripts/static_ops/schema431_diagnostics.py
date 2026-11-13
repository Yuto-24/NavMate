"""Recover bounded failure details without changing the fixed tooling's execution."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

if __package__:
    from . import schema431_bundle as bundle
else:
    import schema431_bundle as bundle

OUTPUT_LIMIT = 16 * 1024
SECRET_NAMES = ("GH_TOKEN", "CLOUDFLARE_API_TOKEN", "STATIC_GOOGLE_ACCESS_TOKEN")


def build_command(app, args: list[str], cwd: Path, root: Path, store: Path) -> str | None:
    """Admit only the exact build commands from the pinned Operator.build()."""
    image = "autonavlog-static-release:" + bundle.TOOLING
    if cwd == root and args == [
        "docker", "build", "-f", "scripts/static_ops/Dockerfile.build", "-t", image, "."
    ]:
        return "docker-build"
    for destination in (store / "prepared", store / "fresh"):
        if cwd == root and args == [
            sys.executable, str(root / "scripts/prepare_msm_feed.py"),
            "--output", str(destination / "feed"), "--cache", str(destination / "cache"),
            "--hours", str(app.PUBLICATION_GENERATION_HOURS), "--full-run",
        ]:
            return "msm-producer"
        container = [
            "docker", "run", "--rm", "-i", "--mount",
            f"type=bind,source={destination / 'app'},target=/app", "--mount",
            f"type=bind,source={destination / 'feed'},target=/feed,readonly",
        ]
        for name in app.gate.CONFIGURATION:
            container += ["--env", name]
        container += [
            "--env", "AUTONAVLOG_MSM_FEED=/feed", "--env",
            "AUTONAVLOG_REFERENCE_PYTHON=python3", "--env", f"ARTIFACT_UID={os.getuid()}",
            "--env", f"ARTIFACT_GID={os.getgid()}", image, "sh", "-eu", "-s",
        ]
        if cwd == root and args == container:
            return "candidate-build-tests"
        if cwd == root and args == [
            "node", str(root / "web/scripts/check-static.mjs"),
            str(destination / "upload/dist-static"),
        ]:
            return "static-artifact-check"
    return None


def private_tail(value: object, env: dict, limit: int = OUTPUT_LIMIT) -> dict:
    """Redact known credentials before truncation so no token fragment is retained."""
    text = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value
    text = text if isinstance(text, str) else ""
    secrets = {env[name] for name in SECRET_NAMES if env.get(name)}
    for secret in sorted(secrets, key=len, reverse=True):
        text = text.replace(secret, "[REDACTED]")
    encoded = text.encode("utf-8", errors="replace")
    return {"tail": encoded[-limit:].decode("utf-8", errors="ignore"),
            "truncated": len(encoded) > limit}


def record_failure(app, error: Exception, root: Path, journal, env: dict) -> None:
    """Add private diagnostics; collection failures cannot change the original outcome.

    command() already captured its child's result. Its exception traceback retains
    that CompletedProcess even though the original function does not return it.
    Read that one trusted frame, never replace command()/subprocess or replay it.
    """
    try:
        details = {"exception_type": type(error).__name__, "stack": []}
        # Blocked has a fixed-message contract. Native exceptions can contain
        # provider responses, so retain their type/location without their message.
        if type(error) is app.Blocked:
            details["message"] = private_tail(str(error), env, 2048)
        traceback = error.__traceback__
        while traceback is not None:
            frame = traceback.tb_frame
            details["stack"].append({"file": Path(frame.f_code.co_filename).name,
                                     "function": frame.f_code.co_name,
                                     "line": traceback.tb_lineno})
            details["stack"] = details["stack"][-12:]
            if frame.f_code is app.command.__code__:
                local = frame.f_locals
                kind = build_command(app, local.get("args"), local.get("cwd"), root,
                                     journal.path.parent)
                result = local.get("result")
                if kind is not None:
                    command = {"kind": kind, "result": "unavailable"}
                    if isinstance(result, subprocess.CompletedProcess):
                        command.update(result="completed", returncode=result.returncode,
                                       stdout=private_tail(result.stdout, env),
                                       stderr=private_tail(result.stderr, env))
                    elif isinstance(error.__context__, subprocess.TimeoutExpired):
                        command["result"] = "timeout"
                    elif isinstance(error.__context__, OSError):
                        command["result"] = "spawn-error"
                    details["command"] = command
            traceback = traceback.tb_next
        candidate = {**journal.value, "failure": details}
        # The existing encrypted journal has a fixed byte budget. Diagnostics
        # must not turn an otherwise recoverable failure into an archive failure.
        if len(json.dumps(candidate, indent=2, sort_keys=True).encode()) + 1 > bundle.MAX_RECORD:
            command = details.get("command", {})
            command.pop("stdout", None)
            command.pop("stderr", None)
            details["output_omitted"] = "journal-size-limit"
        if len(json.dumps(candidate, indent=2, sort_keys=True).encode()) + 1 > bundle.MAX_RECORD:
            return
        previous = journal.value.get("failure")
        journal.value["failure"] = details
        try:
            journal.save()
        except Exception:
            if previous is None:
                journal.value.pop("failure", None)
            else:
                journal.value["failure"] = previous
    except Exception:
        # The established BLOCKED, archive and cleanup paths remain authoritative.
        return

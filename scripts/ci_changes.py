"""Select complete CI suites for known PR inputs; unknown changes run everything."""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Change:
    path: str
    old_mode: str
    new_mode: str


def git(root: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(root), *args], stderr=subprocess.PIPE)


def commit_sha(value: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{40}", value) or value == "0" * 40:
        raise ValueError("Missing or invalid commit SHA")
    return value


def changed_files(root: Path, event_name: str, event: dict) -> list[Change]:
    if event_name == "pull_request":
        base = commit_sha(event["pull_request"]["base"]["sha"])
        head = commit_sha(event["pull_request"]["head"]["sha"])
        base = git(root, "merge-base", base, head).decode().strip()
    elif event_name == "push":
        base = commit_sha(event["before"])
        head = commit_sha(event["after"])
    else:
        raise ValueError("Unsupported event")

    # Disable rename detection so moving code into docs still includes its deletion.
    # NUL delimiters preserve paths containing whitespace or newlines, without an API file limit.
    raw = git(root, "diff", "--raw", "--no-abbrev", "--no-renames", "-z", base, head, "--")
    if not raw:
        return []
    fields = raw.split(b"\0")
    if fields.pop() != b"" or len(fields) % 2:
        raise ValueError("Invalid Git diff")
    changes = []
    for index in range(0, len(fields), 2):
        old_mode, new_mode, _, _, _ = fields[index].decode("ascii").split()
        if not old_mode.startswith(":"):
            raise ValueError("Invalid Git diff mode")
        changes.append(Change(os.fsdecode(fields[index + 1]), old_mode[1:], new_mode))
    return changes


def is_documentation(change: Change) -> bool:
    # Symlinks, submodules and executable-mode changes require the full checks.
    if {change.old_mode, change.new_mode} - {"000000", "100644"}:
        return False
    if change.path == "README.md":
        # Packaging needs the root README to exist as a regular file.
        return change.new_mode == "100644"
    return change.path == "AGENTS.md" or (
        change.path.startswith("docs/") and change.path.endswith(".md")
    )


JOBS = frozenset(
    {
        "pytest",
        "runtime",
        "web",
        "taf-proxy",
        "local-browser",
        "account-sync",
        "static-tooling-install",
        "msm-trigger",
    }
)
WEB_JOBS = frozenset({"web", "local-browser", "account-sync"})
PYTHON_JOBS = WEB_JOBS | {"pytest", "runtime", "static-tooling-install"}


def affected_jobs(change: Change) -> frozenset[str]:
    if is_documentation(change):
        return frozenset()
    # New file types, symlinks, submodules and permission changes are not classified.
    if {change.old_mode, change.new_mode} - {"000000", "100644"}:
        return JOBS
    path = change.path
    if path.startswith("web/src/") and path.endswith((".ts", ".tsx", ".css")):
        # UI and application state share auth, persistence and sync consumers.
        return WEB_JOBS
    if path.startswith("src/autonavlog/") and path.endswith(".py"):
        # The installed backend is also bundled into the browser and feed tooling.
        return PYTHON_JOBS
    if path == "services/taf-proxy/worker.mjs":
        return frozenset({"taf-proxy", "web", "local-browser"})
    if path in {"services/msm-trigger/worker.ts", "services/msm-trigger/entrypoint.ts"}:
        return frozenset({"msm-trigger"})
    # Tests, CI, data, release/build inputs, dependencies and unknown paths are cross-cutting.
    return JOBS


def ci_scope(root: Path, event_name: str, event: dict) -> tuple[frozenset[str], str]:
    # Every supported branch push (including docs-only main merges) and manual run is full.
    if event_name != "pull_request":
        return JOBS, "Non-PR event; running full CI."
    try:
        changes = changed_files(root, event_name, event)
    except (KeyError, TypeError, ValueError, OSError, subprocess.CalledProcessError):
        return JOBS, "Changed files could not be determined; running full CI."
    if not changes:
        return JOBS, "No changed files were found; running full CI."
    jobs = frozenset().union(*(affected_jobs(change) for change in changes))
    if not jobs:
        return jobs, f"Documentation-only change ({len(changes)} files); source checks only."
    selected = ", ".join(sorted(jobs))
    return jobs, f"Changed {len(changes)} files; selected complete suites: {selected}."


def main(root: Path | None = None) -> None:
    root = root or Path(__file__).resolve().parents[1]
    try:
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
    except (KeyError, ValueError, OSError):
        jobs, reason = JOBS, "Event payload could not be read; running full CI."
    else:
        jobs, reason = ci_scope(root, os.environ.get("GITHUB_EVENT_NAME", ""), event)
    output = "".join(
        f"run_{job.replace('-', '_')}={str(job in jobs).lower()}\n" for job in sorted(JOBS)
    )
    print(reason)
    print(output, end="")
    if output_path := os.environ.get("GITHUB_OUTPUT"):
        with Path(output_path).open("a", encoding="utf-8") as stream:
            stream.write(output)
    if summary_path := os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(summary_path).open("a", encoding="utf-8") as stream:
            stream.write(f"## CI scope\n\n{reason}\n\n| Suite | Required |\n| --- | --- |\n")
            for job in sorted(JOBS):
                stream.write(f"| {job} | {'yes' if job in jobs else 'no (skipped)'} |\n")


if __name__ == "__main__":
    main()

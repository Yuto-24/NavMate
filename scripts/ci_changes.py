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
    if change.path == "AGENTS.md":
        return True
    # Documentation and review evidence are passive inputs. Keep executable files,
    # unfamiliar types and documents consumed by code/tests in the full suite.
    if change.path in {
        "docs/evidence/airport-vor-departure.json",
        "docs/reference/vrep-169-confirmed-source.md",
        "docs/release-2-3-2-copy-request.json",
    }:
        return False
    return change.path.startswith("docs/") and Path(change.path).suffix.lower() in {
        ".md", ".json", ".txt", ".png", ".xlsx", ".csv", ".sha256", ".gz",
    }


JOBS = frozenset(
    {
        "release-build",
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
# The dedicated spec runs in web's application suite. The rendered Fuel Plan
# and its PNG export are exercised by local-browser.
DISPLAY_PATHS = frozenset({"web/src/fuelPlanDisplay.ts", "web/e2e/fuel-plan-display.spec.ts"})
DISPLAY_JOBS = frozenset({"web", "local-browser"})
# Presentation and its dedicated browser specs do not participate in Project saves.
MAP_DISPLAY_PATHS = frozenset({
    "web/src/components/MapBackground.tsx",
    "web/src/components/SeaCell.tsx",
    "web/src/seaDisplay.ts",
    "web/e2e/map-background.spec.ts",
    "web/e2e/sea-display.spec.ts",
})
APPLICATION_SPECS = frozenset({
    "auth-unit", "map-route-unit", "persistence-unit", "sync-payload-unit", "sync-unit",
    "terrain-unit",
})
LOCAL_SPECS = frozenset({
    "auth", "map-checkpoint", "route-planning", "terrain-browser",
})
ACCOUNT_SPECS = frozenset({
    "dev-shared", "dev-shared-firestore",
})
PYTHON_JOBS = WEB_JOBS | {"pytest", "runtime", "static-tooling-install"}


def classify(change: Change) -> tuple[frozenset[str], str]:
    if is_documentation(change):
        return frozenset(), "Documentation"
    # New file types, symlinks, submodules and permission changes are not classified.
    if {change.old_mode, change.new_mode} - {"000000", "100644"}:
        return JOBS, "Unclassified file mode"
    path = change.path
    if path in {"VERSION", "CHANGELOG.md"} and change.new_mode == "100644":
        return frozenset({"release-build"}), "Release metadata"
    if path in MAP_DISPLAY_PATHS:
        return DISPLAY_JOBS, "Map or SEA display"
    spec = re.fullmatch(r"web/e2e/([a-z-]+)\.spec\.ts", path)
    if spec:
        name = spec.group(1)
        if name in APPLICATION_SPECS:
            return frozenset({"web"}), "Application tests"
        # web also collects the Local shards, sync components and emulator contracts.
        if name in {"map-route", "persistence", "sea", "sync-component"}:
            return DISPLAY_JOBS, "Local browser tests and Web collection"
        if name in {"firestore-sync", "storage-upgrade", "sync"}:
            return frozenset({"web", "account-sync"}), "Account tests and Web collection"
        if name in LOCAL_SPECS:
            return frozenset({"local-browser"}), "Local browser tests"
        if name in ACCOUNT_SPECS:
            return frozenset({"account-sync"}), "Account and storage tests"
    if path in DISPLAY_PATHS:
        return DISPLAY_JOBS, "Fuel Plan display only"
    if path.startswith("web/src/") and path.endswith((".ts", ".tsx", ".css")):
        # UI and application state share auth, persistence and sync consumers.
        return WEB_JOBS, "Web source"
    if path.startswith("src/autonavlog/") and path.endswith(".py"):
        # The installed backend is also bundled into the browser and feed tooling.
        return PYTHON_JOBS, "Python source"
    # Both package test commands collect service-local test files at this depth.
    worker_test = re.fullmatch(
        r"services/(msm-trigger|taf-proxy)/[A-Za-z0-9_][A-Za-z0-9_.-]*\.test\.mjs", path
    )
    if worker_test:
        return frozenset({worker_test.group(1)}), f"{worker_test.group(1)} dedicated tests"
    if path == "services/taf-proxy/worker.mjs":
        return frozenset({"taf-proxy", "web", "local-browser"}), "taf-proxy Worker source"
    if path in {"services/msm-trigger/worker.ts", "services/msm-trigger/entrypoint.ts"}:
        return frozenset({"msm-trigger"}), "msm-trigger Worker source"
    # Other tests, CI, data, other build inputs, dependencies and unknown paths are cross-cutting.
    return JOBS, "Shared or unclassified input"


def ci_scope(root: Path, event_name: str, event: dict) -> tuple[frozenset[str], str, bool]:
    # Every supported branch push (including docs-only main merges) and manual run is full.
    if event_name != "pull_request":
        return JOBS, "Non-PR event; running full CI.", False
    try:
        changes = changed_files(root, event_name, event)
    except (KeyError, TypeError, ValueError, OSError, subprocess.CalledProcessError):
        return JOBS, "Changed files could not be determined; running full CI.", False
    if not changes:
        return JOBS, "No changed files were found; running full CI.", False
    classified = [(change.path, classify(change)) for change in changes]
    rules = {rule for _, rule in classified}
    local_inputs = {path for path, (suites, _) in classified if "local-browser" in suites}
    jobs = frozenset().union(*(suites for suites, _ in rules))
    auth_tests = {"web/e2e/auth.spec.ts", "web/e2e/sync-component.spec.ts"}
    skip_local_auth = (
        bool(local_inputs) and "account-sync" not in jobs and local_inputs.isdisjoint(auth_tests)
    )
    reasons = []
    for suites, label in sorted(rules, key=lambda rule: rule[1]):
        selected = ", ".join(sorted(suites)) or "source checks only"
        reasons.append(f"- {label} → {'full CI' if suites == JOBS else selected}")
    if skip_local_auth:
        reasons.append(
            "- Local browser auth suite skipped: selected inputs do not affect authentication or sync."
        )
    return jobs, "\n".join(reasons), skip_local_auth


def main(root: Path | None = None) -> None:
    root = root or Path(__file__).resolve().parents[1]
    try:
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
    except (KeyError, ValueError, OSError):
        jobs, reason = JOBS, "Event payload could not be read; running full CI."
        skip_local_auth = False
    else:
        jobs, reason, skip_local_auth = ci_scope(
            root, os.environ.get("GITHUB_EVENT_NAME", ""), event
        )
    output = "".join(
        f"run_{job.replace('-', '_')}={str(job in jobs).lower()}\n" for job in sorted(JOBS)
    )
    output += f"skip_local_auth={str(skip_local_auth).lower()}\n"
    print(reason)
    print(output, end="")
    if output_path := os.environ.get("GITHUB_OUTPUT"):
        with Path(output_path).open("a", encoding="utf-8") as stream:
            stream.write(output)
    if summary_path := os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(summary_path).open("a", encoding="utf-8") as stream:
            stream.write(
                f"## CI scope\n\n{reason}\n\n"
                "Always required: release-sources and ci-required.\n\n"
                "| Suite | Required |\n| --- | --- |\n"
            )
            for job in sorted(JOBS):
                stream.write(f"| {job} | {'yes' if job in jobs else 'no (skipped)'} |\n")


if __name__ == "__main__":
    main()

"""Private GitHub review records. Digests bind an explicit dispatch to exact bytes.

This module never treats tests, a generated report, or an Issue's open state as
review approval. The authenticated human dispatch and its digest are required.
"""

from __future__ import annotations

import hmac
import json
import os
import re
from datetime import UTC, datetime, timedelta

from scripts.static_ops import app_release as app

PREFIX = "NavMate migration review v1\n\n```json\n"
SUFFIX = "\n```\n"
MAX_BYTES = 60_000


def signed_evidence(value: dict, key: bytes) -> dict:
    """Bind generated observations, not a human review, to the trusted runner."""
    app.require("signature" not in value, "Evidence already sealed")
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    signature = hmac.digest(key, b"NavMate-migration-evidence-v1\0" + raw, "sha256").hex()
    return {**value, "signature": signature}


def verify_evidence(value: dict, key: bytes) -> None:
    unsigned = {name: item for name, item in value.items() if name != "signature"}
    expected = signed_evidence(unsigned, key)["signature"]
    app.require(
        isinstance(value.get("signature"), str)
        and hmac.compare_digest(value["signature"], expected),
        "Evidence was not sealed by the trusted workflow or has changed",
    )


def body_for(value: dict) -> str:
    phase = value["phase"]
    instructions = {
        "evidence": "Independently review source compatibility and each test result. Tests are not approval. Then select prepare-migration with this Issue number and the record SHA-256 from the Actions summary. Preparation pauses weather updates.",  # noqa: E501
        "prepared": "Weather updates are paused. This plan expires 30 minutes after preparation. Review the exact plan and changes below. To authorize production publication, select publish-migration with this comment ID and the record SHA-256 from the Actions summary.",  # noqa: E501
        "published": "Publication and readback completed. Confirm the recorded approved commit SHA and weather update state.",  # noqa: E501
        "blocked": "Publication is blocked or incomplete. Inspect canonical Pages, approved SHA, and weather state before recovery. Do not replay uncertain writes or resume weather unconditionally.",  # noqa: E501
    }
    summary = [
        "## Migration " + phase,
        "",
        instructions[phase],
        "",
        "Candidate: `" + value["candidate_sha"] + "`",
        "",
    ]
    if phase == "evidence":
        identity = value["identity"]
        summary += [
            "Current: `" + identity["current_sha"] + "`",
            "Tooling: `" + identity["tooling_sha"] + "`",
            "",
        ]
        summary += [
            "- " + name + ": " + check["result"] + " — " + check["summary"]
            for name, check in value["checks"].items()
        ]
        summary += [
            "",
            "Synthetic data and emulator results do not establish live account or real-device acceptance.",  # noqa: E501
            "",
        ]
    origin = value.get("origin_run", value.get("handoff", {}).get("origin_run", {}))
    run_id = origin.get("run_id", "")
    if isinstance(run_id, str) and re.fullmatch(r"[1-9]\d{0,19}", run_id):
        summary += [f"[Actions summary](https://github.com/{app.REPO}/actions/runs/{run_id})", ""]
    summary += [f"[Migration runbook](https://github.com/{app.REPO}/blob/main/docs/"
                "schema_transition.md#github上の移行証跡と承認)", ""]
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return "\n".join(summary) + PREFIX + raw + SUFFIX


class Reviews:
    def __init__(self, operator):
        self.operator = operator
        self.repository = os.environ.get("STATIC_MIGRATION_REVIEW_REPOSITORY", "")
        self.token = os.environ.get("STATIC_MIGRATION_REVIEW_TOKEN", "")
        app.require(
            re.fullmatch(r"Yuto-24/[A-Za-z0-9_.-]+", self.repository)
            and self.repository != app.REPO
            and self.token,
            "Configure an owner-controlled private migration review repository",
        )
        repository = self.api("")
        self.repository_id = repository.get("id")
        self.require_private(repository)

    def require_private(self, repository=None):
        repository = self.api("") if repository is None else repository
        app.require(
            repository.get("private") is True
            and repository.get("full_name") == self.repository
            and repository.get("owner", {}).get("id") == 65487096
            and type(self.repository_id) is int
            and self.repository_id > 0
            and repository.get("id") == self.repository_id,
            "Migration evidence repository must remain private and owner-controlled",
        )

    def open_issue(self, number):
        app.require(type(number) is int and number > 0, "Invalid private review Issue")
        issue = self.api(f"issues/{number}")
        app.require(
            issue.get("number") == number
            and issue.get("state") == "open"
            and "pull_request" not in issue,
            "Migration review was withdrawn or is unavailable",
        )
        return issue

    def api(self, path, method="GET", body=None):
        # Keep this narrowly scoped credential out of producer/build subprocesses.
        result = app.command(
            [
                "gh",
                "api",
                "--hostname",
                "github.com",
                "--method",
                method,
                "graphql" if path == "graphql" else
                ("repos/" + self.repository + "/" + path).rstrip("/"),
                *(["--input", "-"] if body is not None else []),
            ],
            env={
                "PATH": os.environ.get("PATH", os.defpath),
                "GH_TOKEN": self.token,
                "GH_PROMPT_DISABLED": "1",
            },
            input_text=json.dumps(body) if body is not None else None,
        )
        return json.loads(result)

    def save(self, value: dict, *, issue: int | None = None) -> dict:
        self.require_private()
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"))
        app.require(len(raw.encode()) <= MAX_BYTES, "Private review record too large")
        body = body_for(value)
        app.require(len(body.encode()) <= MAX_BYTES, "Private review record too large")
        digest = app.digest(body.encode())
        if issue is None:
            result = self.api(
                "issues",
                "POST",
                {"title": "Migration " + value["candidate_sha"][:12], "body": body},
            )
            reference = {"type": "issue", "id": result["number"], "issue": result["number"]}
        else:
            self.open_issue(issue)
            result = self.api(f"issues/{issue}/comments", "POST", {"body": body})
            reference = {"type": "comment", "id": result["id"], "issue": issue}
        # An uncertain POST is never replayed. The operator reconciles the private Issue.
        app.require(result.get("body") == body, "Private record write was not confirmed")
        self.require_private()
        return {
            **reference,
            "sha256": digest,
            "url": f"https://github.com/{self.repository}/issues/{reference['issue']}",
        }

    def read(self, number: str, expected: str, *, comment=False) -> dict:
        self.require_private()
        app.require(
            re.fullmatch(r"[1-9]\d{0,19}", number) and re.fullmatch(r"[0-9a-f]{64}", expected),
            "Exact private record identity and reviewed digest required",
        )
        endpoint = "issues/" + ("comments/" if comment else "") + number
        result = self.api(endpoint)
        if comment:
            # REST supplies only the node identity. Never combine its body with
            # a later parent state: read both from the same GraphQL observation.
            node_id = result.get("node_id")
            app.require(isinstance(node_id, str) and node_id, "Comment identity unavailable")
            response = self.api("graphql", "POST", {
                "query": """query($id: ID!) { node(id: $id) { ... on IssueComment {
                    fullDatabaseId body
                    issue { number state repository { databaseId nameWithOwner isPrivate } }
                } } }""",
                "variables": {"id": node_id},
            })
            app.require(not response.get("errors"), "Private comment observation failed")
            result = (response.get("data") or {}).get("node")
            app.require(
                isinstance(result, dict) and str(result.get("fullDatabaseId")) == number,
                "Private comment identity changed",
            )
        else:
            app.require(
                result.get("number") == int(number)
                and result.get("state") == "open"
                and "pull_request" not in result,
                "Migration review was withdrawn or is unavailable",
            )
        body = result.get("body", "")
        app.require(
            isinstance(body, str)
            and body.count(PREFIX) == 1
            and body.endswith(SUFFIX)
            and len(body.encode()) <= MAX_BYTES + len(PREFIX) + len(SUFFIX),
            "Invalid private review record",
        )
        raw = body.split(PREFIX, 1)[1][: -len(SUFFIX)]
        app.require(app.digest(body.encode()) == expected, "Reviewed private record changed")
        value = json.loads(raw)
        app.require(body_for(value) == body, "Private review summary changed")
        app.require(
            type(value.get("schema_version")) is int and value["schema_version"] == 1,
            "Unsupported private review record",
        )
        if comment:
            issue = value.get("issue")
            parent = result.get("issue") or {}
            app.require(
                type(issue) is int and issue > 0 and parent.get("number") == issue
                and parent.get("repository") == {
                    "databaseId": self.repository_id,
                    "nameWithOwner": self.repository,
                    "isPrivate": True,
                },
                "Prepared review belongs to another Issue",
            )
            app.require(parent.get("state") == "OPEN", "Migration review was withdrawn")
        created = app.instant(value["created_at"])
        app.require(
            datetime.now(UTC) - timedelta(hours=24) <= created <= datetime.now(UTC),
            "Evidence expired; generate and review fresh evidence",
        )
        self.require_private()
        return value


def approved_actor(operator, env: dict) -> str:
    """Validate the real dispatch identity; never invent an independent reviewer."""
    actor = env.get("GITHUB_ACTOR", "")
    app.require(
        re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})", actor), "Human approval actor required"
    )
    user = operator.gh("collaborators/" + actor + "/permission")
    app.require(
        user.get("permission") in ("admin", "maintain", "write")
        and user.get("user", {}).get("login") == actor
        and user["user"].get("type") == "User",
        "Authorized human approval required",
    )
    return actor


def attest(evidence: dict, reviewer: str, directory) -> dict:
    app.require(
        evidence.get("phase") == "evidence"
        and evidence.get("result") == "PASS"
        and evidence.get("publication_authorized") is False,
        "Successful evidence required; approval cannot override a failed check",
    )
    record = evidence["identity"]
    app.require("checks" not in record, "Unreviewed evidence must not contain attestations")
    record = {**record, "checks": {}}
    for role in ("old_to_new", "old_writer_fenced", "storage_sync_roundtrip"):
        check = evidence["checks"][role]
        app.require(
            check.get("result") == "PASS" and check.get("summary"),
            "All migration checks must pass before review",
        )
        report = {
            "identity": evidence["identity"],
            "check": role,
            "result": "PASS",
            "reviewed_by": reviewer,
            "summary": check["summary"],
            "observations": check["observations"],
        }
        path = directory / (role + ".json")
        app.write_json(path, report)
        record["checks"][role] = {
            "result": "PASS",
            "reviewed_by": reviewer,
            "summary": report["summary"],
            "record": {"path": path.name, "sha256": app.digest(path.read_bytes())},
        }
    app.write_json(directory / "SCHEMA_RECORD.json", record)
    return record

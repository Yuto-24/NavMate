"""Firestore migration review records. Digests bind dispatch to exact JSON bytes.

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
from scripts.static_ops import migration_firestore as firestore


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


def record_id(env, phase):
    app.require(phase in {"evidence", "prepared", "published", "blocked", "revoked"},
                "Invalid evidence phase")
    run, attempt = env.get("GITHUB_RUN_ID", ""), env.get("GITHUB_RUN_ATTEMPT", "")
    app.require(all(re.fullmatch(r"[1-9]\d{0,19}", item) for item in (run, attempt)),
                "Exact evidence run identity required")
    return f"r{run}-a{attempt}-{phase}"


def checked_id(value):
    app.require(isinstance(value, str) and re.fullmatch(
        r"r[1-9]\d{0,19}-a[1-9]\d{0,19}-(evidence|prepared|published|blocked|revoked)", value),
        "Firestore record ID required; regenerate legacy Issue/comment evidence")
    return value


def envelope(raw, root_id, attachments=None):
    value = json.loads(raw)
    return {"root_id": root_id, "original_json": raw, "display": firestore.display(value),
            "sha256": app.digest(raw.encode()), "attachments": attachments or {}}


class Reviews:
    """Immutable originals and a small transactional lifecycle per evidence set.

    One prepare and one publication are admitted per evidence set. Failed or
    uncertain attempts require new evidence. A revocation tombstone is permanent.
    """

    def __init__(self, operator=None, *, database=None, env=None, allow_disabled=False):
        self.env = dict(os.environ) if env is None else env
        self.db = database or firestore.configured(self.env, allow_disabled=allow_disabled)

    def reference(self, id, digest):
        return {"id": checked_id(id), "sha256": digest,
                "url": "https://console.firebase.google.com/project/" + self.db.project
                       + "/firestore/databases/-default-/data"}

    def document(self, id, expected, tx):
        checked_id(id)
        app.require(isinstance(expected, str) and re.fullmatch(r"[0-9a-f]{64}", expected),
                    "Reviewed record SHA-256 required")
        document = self.db.get("migrationRecords/" + id, tx)
        app.require(isinstance(document, dict) and document.get("sha256") == expected,
                    "Reviewed record missing or changed")
        raw = document["original_json"]
        app.require(app.digest(raw.encode()) == expected, "Reviewed record changed")
        value = json.loads(raw)
        app.require(
            firestore.same(document, envelope(raw, document["root_id"], document["attachments"])),
            "Review original and display differ")
        app.require(type(value.get("schema_version")) is int and value["schema_version"] == 1,
                    "Unsupported review record")
        attachments = document["attachments"]
        required = {}
        if value["phase"] == "evidence" and "sample_sha256" in value["checks"][
                "old_to_new"]["observations"]:
            required["sample"] = value["checks"]["old_to_new"]["observations"]["sample_sha256"]
        if value["phase"] == "prepared":
            required["plan"] = value["plan_sha256"]
        app.require(attachments == required, "Review attachment manifest changed")
        for label, digest in required.items():
            part = self.db.get("migrationRecords/" + id + "-" + label, tx)
            app.require(isinstance(part, dict), "Review attachment missing")
            app.require(firestore.same(part, envelope(part["original_json"], document["root_id"]))
                        and part["sha256"] == digest, "Review attachment changed")
            if label == "plan":
                app.require(firestore.same(json.loads(part["original_json"]), value["plan"]),
                            "Exact plan differs from review")
        return value, document

    def observe(self, id, expected, tx, *, active=True):
        value, document = self.document(id, expected, tx)
        root = checked_id(document["root_id"])
        group = self.db.get("migrationGroups/" + root, tx)
        app.require(isinstance(group, dict) and group.get("root_id") == root,
                    "Evidence lifecycle unavailable")
        tombstone = self.db.get("migrationRevocations/" + root, tx)
        if active:
            app.require(tombstone is None and group.get("revoked") is False,
                        "Migration review was revoked; generate new evidence")
            app.require(group.get("state") != "BLOCKED", "Evidence has an incomplete operation")
        if value["phase"] == "evidence":
            app.require(id == root and group["evidence"] == {"id": id, "sha256": expected},
                        "Evidence parent changed")
        elif value["phase"] == "prepared":
            parent = value["evidence_reference"]
            app.require(parent == group["evidence"] and parent["id"] == root
                        and group["prepared"] == {"id": id, "sha256": expected},
                        "Prepared evidence parent changed")
            original, _ = self.document(root, parent["sha256"], tx)
            if active:
                self.fresh(original)
        else:
            app.require(not active, "Evidence or prepared plan required")
        if active:
            self.fresh(value)
        return value, group

    @staticmethod
    def fresh(value):
        created = app.instant(value["created_at"])
        now = datetime.now(UTC)
        app.require(now - timedelta(hours=24) <= created <= now,
                    "Evidence expired; generate and review fresh evidence")
        if value["phase"] == "prepared":
            prepared = app.instant(value["plan"]["prepared_at"])
            app.require(now - timedelta(minutes=30) <= prepared <= now,
                        "Plan expired; generate new evidence")

    def read(self, id, expected, *, comment=False):
        with self.db.transaction() as tx:
            value, _ = self.observe(id, expected, tx)
            app.require(value["phase"] == ("prepared" if comment else "evidence"),
                        "Wrong review phase")
            return value

    def commit_known(self, writes, known, tx):
        try:
            self.db.commit(writes, tx)
        except Exception:
            # Never replay writes, even when the server may have committed them.
            # Reconcile exact known document IDs using a fresh consistent snapshot.
            with self.db.transaction() as check:
                app.require(all(firestore.same(self.db.get(path, check), value)
                                for path, value in known.items()),
                            "Evidence write outcome unknown; do not retry")

    def begin(self, id, expected, operation):
        app.require(operation in ("prepare", "publish"), "Invalid lifecycle operation")
        with self.db.transaction(write=True) as tx:
            value, group = self.observe(id, expected, tx)
            phase = "evidence" if operation == "prepare" else "prepared"
            state = "EVIDENCE" if operation == "prepare" else "PREPARED"
            app.require(value["phase"] == phase and group["state"] == state,
                        "Evidence already used; generate new evidence")
            claim = record_id(self.env, "prepared" if operation == "prepare" else "published")
            group = {**group, "state": "PREPARING" if operation == "prepare" else "PUBLISHING",
                     "claim": claim}
            path = "migrationGroups/" + group["root_id"]
            self.commit_known([self.db.put(path, group, create=False)], {path: group}, tx)
        return value

    def save(self, value, *, root=None, sample_json=None, plan_json=None):
        phase = value["phase"]
        id = record_id(self.env, phase)
        root = checked_id(root) if root else id
        parts = {name: raw for name, raw in (("sample", sample_json), ("plan", plan_json))
                 if raw is not None}
        attachments = {name: app.digest(raw.encode()) for name, raw in parts.items()}
        raw = firestore.canonical(value)
        document = envelope(raw, root, attachments)
        # Attachments are already bound by fields in the exact original record.
        if sample_json is not None:
            app.require(attachments["sample"] == value["checks"]["old_to_new"][
                "observations"]["sample_sha256"], "Synthetic sample hash mismatch")
        if phase == "prepared":
            app.require(plan_json is not None and attachments["plan"] == value["plan_sha256"]
                        and firestore.same(json.loads(plan_json), value["plan"]),
                        "Exact plan required")
        known = {"migrationRecords/" + id: document}
        known.update({"migrationRecords/" + id + "-" + label: envelope(content, root)
                      for label, content in parts.items()})
        with self.db.transaction(write=True) as tx:
            path = "migrationGroups/" + root
            group = self.db.get(path, tx)
            tombstone = self.db.get("migrationRevocations/" + root, tx)
            if group is None:
                app.require(root == id and phase in ("evidence", "blocked"),
                            "Evidence lifecycle missing")
                group = {"root_id": root, "state": "EVIDENCE" if phase == "evidence" else "BLOCKED",
                         "revoked": False, "evidence": {"id": id, "sha256": document["sha256"]},
                         "prepared": {}, "published": {}, "blocked": {}, "claim": ""}
                create = True
            else:
                create = False
                app.require(phase != "blocked" or group["state"] != "PUBLISHED",
                            "Published evidence cannot become blocked")
                if phase != "blocked":
                    app.require(tombstone is None and group["revoked"] is False,
                                "Migration review was revoked")
                    expected_state = "PREPARING" if phase == "prepared" else "PUBLISHING"
                    app.require(phase in ("prepared", "published")
                                and group["state"] == expected_state and group["claim"] == id,
                                "Migration operation claim changed")
                    app.require(value["evidence_reference"] == group["evidence"],
                                "Evidence parent changed")
                if phase == "published":
                    app.require(value.get("final_verified") is True
                                and value["prepared_reference"] == group["prepared"],
                                "Final publication verification required")
                    group["completed_at"] = value["created_at"]
                group[phase if phase != "blocked" else "blocked"] = {
                    "id": id, "sha256": document["sha256"]}
                group["state"] = {"prepared": "PREPARED", "published": "PUBLISHED",
                                  "blocked": "BLOCKED"}[phase]
                group["claim"] = ""
            known[path] = group
            writes = [self.db.put(name, item, create=create if name == path else True)
                      for name, item in known.items()]
            self.commit_known(writes, known, tx)
        # Re-read every original, display and attachment, without an expiry shortcut.
        with self.db.transaction() as tx:
            app.require(firestore.same(self.document(id, document["sha256"], tx)[0], value),
                        "Evidence readback mismatch")
        return self.reference(id, document["sha256"])

    def revoke(self, id, expected, actor):
        with self.db.transaction(write=True) as tx:
            value, group = self.observe(id, expected, tx, active=False)
            root = group["root_id"]
            group_path = "migrationGroups/" + root
            app.require(any(group.get(role) == {"id": id, "sha256": expected}
                            for role in ("evidence", "prepared", "published", "blocked")),
                        "Revoked record is not part of this migration group")
            if value["phase"] == "published":
                app.require(value["evidence_reference"] == group["evidence"]
                            and group["evidence"]["id"] == root,
                            "Published evidence parent changed")
            path = "migrationRevocations/" + root
            existing = self.db.get(path, tx)
            if existing is not None:
                app.require(group["revoked"] is True, "Revocation state changed")
                return self.reference(existing["id"], existing["sha256"])
            value = {"schema_version": 1, "phase": "revoked",
                     "created_at": datetime.now(UTC).isoformat(),
                     "record_id": id, "reviewed_record_sha256": expected, "actor": actor}
            revoked_id = record_id(self.env, "revoked")
            document = envelope(firestore.canonical(value), root)
            marker = {"id": revoked_id, "sha256": document["sha256"]}
            group = {**group, "revoked": True}
            known = {path: marker, "migrationRecords/" + revoked_id: document, group_path: group}
            self.commit_known([self.db.put(name, item, create=name != group_path)
                               for name, item in known.items()], known, tx)
            return self.reference(revoked_id, document["sha256"])

    def cleanup(self, now=None):
        now = now or datetime.now(UTC)
        removed = 0
        failed = []
        for root in self.db.groups():
            checked_id(root)
            with self.db.transaction(write=True) as tx:
                path = "migrationGroups/" + root
                group = self.db.get(path, tx)
                if (not group or group.get("state") != "PUBLISHED"
                        or group.get("revoked") is not False):
                    continue
                if group.get("claim") or group.get("blocked") or not group.get("completed_at"):
                    continue
                if now < app.instant(group["completed_at"]) + timedelta(days=30):
                    continue
                if self.db.get("migrationRevocations/" + root, tx) is not None:
                    continue
                paths = [path]
                values = {}
                try:
                    for role in ("evidence", "prepared", "published"):
                        ref = group[role]
                        value, document = self.document(ref["id"], ref["sha256"], tx)
                        app.require(document["root_id"] == root and value["phase"] == role,
                                    "Retention evidence set changed")
                        paths.append("migrationRecords/" + ref["id"])
                        paths.extend("migrationRecords/" + ref["id"] + "-" + label
                                     for label in document["attachments"])
                        values[role] = value
                    app.require(group["evidence"]["id"] == root
                                and values["prepared"]["evidence_reference"] == group["evidence"]
                                and values["published"]["evidence_reference"] == group["evidence"]
                                and values["published"]["prepared_reference"] == group["prepared"]
                                and values["published"].get("final_verified") is True
                                and values["published"]["created_at"] == group["completed_at"],
                                "Retention final verification missing")
                except app.Blocked:
                    failed.append(root)
                    continue  # Keep the entire set; only validation failures are isolated.
                writes = [{"delete": self.db.root + "/" + name} for name in paths]
                self.commit_known(writes, dict.fromkeys(paths), tx)
                removed += 1
        app.require(not failed, "Retention validation failed for record sets: " + ", ".join(failed))
        return removed


def approved_actor(operator, env: dict) -> str:
    """Validate the real dispatch identity; never invent an independent reviewer."""
    actor = env.get("GITHUB_ACTOR", "")
    app.require(
        re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})", actor), "Human approval actor required"
    )
    user = operator.gh("collaborators/" + actor + "/permission")
    app.require(
        actor == "Yuto-24"
        and user.get("permission") in ("admin", "maintain", "write")
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

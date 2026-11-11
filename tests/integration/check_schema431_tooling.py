"""Exercise the unchanged pinned validator with synthetic evidence and real Git sources.

This is not the private production record or permission to prepare. No provider
authentication or API calls, scheduler mutations, builds or publication occur.
"""

import argparse
import json
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/static_ops"))

import schema431_bundle as bundle  # noqa: E402
import schema431_prepare as driver  # noqa: E402


def check(root: Path) -> None:
    app = driver.load_tooling(root)
    assert Path(app.Operator.reviewed_schema.__code__.co_filename).resolve() == (
        root / "scripts/static_ops/app_release.py").resolve()
    assert Path(app.prepare.__code__.co_filename).resolve() == (
        root / "scripts/static_ops/app_release.py").resolve()
    with tempfile.TemporaryDirectory(prefix="schema431-synthetic-") as name:
        temporary = Path(name)
        source = temporary / "source"
        source.mkdir(mode=0o700)
        bundle.EVIDENCE_ROOT = temporary / "evidence"
        operator = driver.manual_operator(app, root, {})
        variables = {key: "synthetic" for key in app.gate.CONFIGURATION}
        variables["VITE_FIREBASE_PROJECT_ID"] = "synthetic-project"
        record = {
            "schema_version": 1, "kind": "forecast-model-selection",
            "sha": bundle.CANDIDATE, "current_sha": bundle.CURRENT,
            "tooling_sha": bundle.TOOLING, "project": variables["VITE_FIREBASE_PROJECT_ID"],
            "origin": app.gate.ORIGIN,
            "configuration_digest": app.fingerprint(app.public_configuration(variables)),
            "direction": "old-to-new", "recovery": "forward-fix; preserve Project data",
            "database_version": 2, "latest_policy": "replace-own-device-latest-on-open",
            "before_blob": operator.source_digest(bundle.CURRENT, app.COMPATIBILITY[2]),
            "after_blob": operator.source_digest(bundle.CANDIDATE, app.COMPATIBILITY[2]),
            "writer_blob": operator.source_digest(bundle.CANDIDATE,
                                                   "web/src/localProjectRepository.ts"),
            "checks": {},
        }
        identity = {key: value for key, value in record.items() if key != "checks"}
        for role in bundle.ROLES:
            report = {
                "identity": identity, "check": role, "result": "PASS",
                "reviewed_by": "synthetic-test-only", "summary": "transport/validator fixture",
            }
            path = source / (role + ".json")
            app.write_json(path, report)
            record["checks"][role] = {
                "result": report["result"], "reviewed_by": report["reviewed_by"],
                "summary": report["summary"],
                "record": {"path": path.name, "sha256": bundle.sha256(path.read_bytes())},
            }
        record_path = source / bundle.RECORD_NAME
        app.write_json(record_path, record)
        # Only this isolated fixture changes the expected raw hash; the workflow
        # has no CLI/env/input override and still requires the real reviewed hash.
        bundle.RECORD_SHA256 = bundle.sha256(record_path.read_bytes())
        packed = temporary / "packed"
        bundle.pack(record_path, packed)
        files = bundle.open_secret((packed / "evidence.secret").read_text(),
                                   bundle.key_bytes((packed / "archive.key").read_text()),
                                   datetime.now(UTC))
        bundle.restore_evidence(files)
        receipt = operator.reviewed_schema(bundle.CANDIDATE, bundle.CURRENT, variables)
        assert receipt["sha256"] == bundle.RECORD_SHA256
        assert len(receipt["evidence"]) == 3
        for change in ("candidate", "project", "missing-report", "report-hash", "report-identity"):
            candidate, config = bundle.CANDIDATE, dict(variables)
            report_path = bundle.EVIDENCE_ROOT / (bundle.ROLES[0] + ".json")
            original_report = report_path.read_bytes()
            if change == "candidate":
                candidate = bundle.CURRENT
            elif change == "project":
                config["VITE_FIREBASE_PROJECT_ID"] = "different-project"
            elif change == "missing-report":
                report_path.unlink()
            elif change == "report-hash":
                report_path.write_bytes(original_report + b"\n")
            else:
                wrong = json.loads(original_report)
                wrong["identity"]["sha"] = bundle.CURRENT
                app.write_json(report_path, wrong)
                record["checks"][bundle.ROLES[0]]["record"]["sha256"] = bundle.sha256(
                    report_path.read_bytes())
                app.write_json(bundle.EVIDENCE_ROOT / bundle.RECORD_NAME, record)
                bundle.RECORD_SHA256 = bundle.sha256(
                    (bundle.EVIDENCE_ROOT / bundle.RECORD_NAME).read_bytes())
            try:
                operator.reviewed_schema(candidate, bundle.CURRENT, config)
            except app.Blocked:
                pass
            else:
                raise AssertionError("Pinned validator accepted invalid synthetic evidence")
            report_path.write_bytes(original_report)
    print(json.dumps({"status": "OK", "tooling_sha": bundle.TOOLING,
                      "synthetic_transport_and_pinned_validator": "PASS",
                      "provider_operations": 0}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tooling", type=Path, required=True)
    check(parser.parse_args().tooling.resolve())

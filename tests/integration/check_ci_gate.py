"""Merge-gate failure cases and the wiring from classifier to workflow jobs."""

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from check_ci_results import check_results, main  # noqa: E402
from ci_changes import JOBS  # noqa: E402


def results(selected=JOBS):
    return {
        "release-sources": {
            "result": "success",
            "outputs": {
                f"run_{job.replace('-', '_')}": str(job in selected).lower() for job in JOBS
            },
        },
        **{job: {"result": "success" if job in selected else "skipped"} for job in JOBS},
    }


@pytest.mark.parametrize(
    "selected", [JOBS, set(), {"msm-trigger"}, {"web", "local-browser", "account-sync"}]
)
def test_full_selected_and_documentation_results(selected):
    assert check_results(results(selected)) == []


@pytest.mark.parametrize("job", ["release-sources", *sorted(JOBS)])
@pytest.mark.parametrize("status", ["failure", "cancelled", "skipped", "pending", None])
def test_required_job_cannot_be_incomplete(job, status):
    needs = results()
    needs[job]["result"] = status
    assert check_results(needs)


@pytest.mark.parametrize("job", sorted(JOBS))
def test_missing_job_and_classification_fail(job):
    needs = results()
    del needs[job]
    assert check_results(needs)
    needs = results()
    del needs["release-sources"]["outputs"][f"run_{job.replace('-', '_')}"]
    assert check_results(needs)


def test_unexpected_execution_is_not_reported_as_intentional_skip():
    needs = results(set())
    needs["web"]["result"] = "failure"
    assert check_results(needs)
    needs["web"]["result"] = "success"
    assert check_results(needs)


def test_cli_reports_actual_skip_and_exits_nonzero_on_failure(tmp_path, monkeypatch):
    summary = tmp_path / "summary.md"
    needs = results({"msm-trigger"})
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setenv("CI_NEEDS", json.dumps(needs))
    main()
    assert "| web | false | skipped |" in summary.read_text()
    needs["msm-trigger"]["result"] = "cancelled"
    monkeypatch.setenv("CI_NEEDS", json.dumps(needs))
    with pytest.raises(SystemExit, match="1"):
        main()


def test_workflow_wires_all_suites_to_fail_closed_gate():
    source = (ROOT / ".github/workflows/test.yml").read_text()
    blocks = dict(
        re.findall(
            r"^  ([a-z][a-z-]+):\n(.*?)(?=^  [a-z][a-z-]+:\n|\Z)",
            source.split("\njobs:\n", 1)[1],
            re.M | re.S,
        )
    )
    assert set(blocks) == JOBS | {
        "release-sources",
        "ci-required",
        "pytest-tests",
        "local-browser-tests",
        "account-sync-tests",
    }
    for job in JOBS:
        output = f"run_{job.replace('-', '_')}"
        assert f"{output}: ${{{{ steps.changes.outputs.{output} }}}}" in blocks["release-sources"]
        for target in [
            job,
            *([f"{job}-tests"] if job in {"pytest", "local-browser", "account-sync"} else []),
        ]:
            condition = (
                "needs.release-sources.result != 'success' || "
                f"needs.release-sources.outputs.{output} != 'false'"
            )
            assert condition in blocks[target]
    gate = blocks["ci-required"]
    needs = re.search(r"needs: \[([^\]]+)\]", gate).group(1)
    assert set(needs.split(", ")) == JOBS | {"release-sources"}
    assert "if: ${{ always() }}" in gate
    assert "CI_NEEDS: ${{ toJSON(needs) }}" in gate
    assert "run: python3 scripts/check_ci_results.py" in gate

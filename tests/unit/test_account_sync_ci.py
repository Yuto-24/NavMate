from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def command_runner(tmp_path):
    binary = tmp_path / "npm"
    binary.write_text(
        '#!/bin/sh\nprintf "%s\\n" "$*" >> "$CALLS"\n[ "$*" != "${FAIL_COMMAND:-}" ]\n'
    )
    binary.chmod(0o755)
    calls = tmp_path / "calls"

    def run(suite, fail="", script="run_account_sync_suite.sh"):
        result = subprocess.run(
            ["sh", str(ROOT / "scripts" / script), *suite],
            env={
                **os.environ,
                "PATH": f"{tmp_path}:{os.environ['PATH']}",
                "CALLS": str(calls),
                "FAIL_COMMAND": fail,
            },
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result, calls.read_text().splitlines() if calls.exists() else []

    return run


@pytest.mark.parametrize("project", ["chromium", "ipad-webkit", "iphone-webkit"])
def test_sync_projects_keep_all_tests_and_worker_setting(command_runner, project):
    result, calls = command_runner([project])
    assert result.returncode == 0
    assert calls == [f"--prefix web run test:sync -- --project={project} --workers=2"]


def test_contracts_keep_rules_storage_and_both_migration_projects(command_runner):
    result, calls = command_runner(["contracts"])
    assert result.returncode == 0
    assert calls == [
        f"--prefix web run test:{suite}" for suite in ["firestore", "storage-upgrade", "migration"]
    ]


@pytest.mark.parametrize("suite", [[], ["unknown"], ["chromium; true"]])
def test_unknown_suite_fails_without_running_a_test(command_runner, suite):
    result, calls = command_runner(suite)
    assert result.returncode == 2
    assert calls == []


def test_failed_rules_stop_remaining_contract_tests(command_runner):
    result, calls = command_runner(["contracts"], "--prefix web run test:firestore")
    assert result.returncode != 0
    assert calls == ["--prefix web run test:firestore"]


def test_workflow_requires_every_isolated_runner_and_complete_selection():
    source = (ROOT / ".github/workflows/test.yml").read_text()
    block = source.split("  account-sync-tests:\n")[1].split("  msm-trigger:\n")[0]
    assert "suite: [chromium, ipad-webkit, iphone-webkit]" in block
    assert "fail-fast: false" in block
    assert "needs: [release-sources, account-sync-tests]" in block
    assert "if: ${{ always() &&" in block
    assert 'run: test "$RESULT" = success' in block
    assert "emulators:exec --only firestore --project demo-autonavlog-sync" in block
    assert '"sh scripts/run_account_sync_suite.sh $SUITE $SHARD"' in block
    web = source.split("  web:\n")[1].split("  taf-proxy:\n")[0]
    assert "node web/scripts/check-account-sync-partition.mjs" in web
    assert "shard: [1, 2]" in block
    assert "- {suite: contracts, shard: 1}" in block
    assert "- {suite: dev-shared, shard: 1}" in block
    assert "name: account-sync-${{ matrix.suite }}-${{ matrix.shard }}-failure" in block


@pytest.mark.parametrize(
    ("suite", "engines"),
    [
        ("chromium", "chromium"),
        ("ipad-webkit", "webkit"),
        ("iphone-webkit", "webkit"),
        ("contracts", "chromium webkit"),
    ],
)
def test_browser_install_matches_suite(command_runner, suite, engines):
    result, calls = command_runner([suite], script="install_account_sync_browsers.sh")
    assert result.returncode == 0
    assert calls == [f"--prefix web exec -- playwright install --with-deps {engines}"]


@pytest.mark.parametrize("suite", [[], ["unknown"], ["chromium; true"]])
def test_browser_install_rejects_unknown_suite(command_runner, suite):
    result, calls = command_runner(suite, script="install_account_sync_browsers.sh")
    assert result.returncode == 2
    assert calls == []


def test_browser_install_failure_is_not_ignored(command_runner):
    result, _ = command_runner(
        ["chromium"],
        "--prefix web exec -- playwright install --with-deps chromium",
        script="install_account_sync_browsers.sh",
    )
    assert result.returncode != 0


def test_browser_jobs_use_matching_preinstalled_image():
    import json

    source = (ROOT / ".github/workflows/test.yml").read_text()
    version = json.loads((ROOT / "web/package.json").read_text())["devDependencies"][
        "@playwright/test"
    ]
    lock = json.loads((ROOT / "web/package-lock.json").read_text())
    assert lock["packages"]["node_modules/@playwright/test"]["version"] == version
    for job, next_job in [
        ("local-browser-tests", "local-browser"),
        ("account-sync-tests", "account-sync"),
    ]:
        block = source.split(f"  {job}:\n")[1].split(f"  {next_job}:\n")[0]
        assert f"image: mcr.microsoft.com/playwright:v{version}-noble" in block
        assert "options: --ipc=host" in block
        assert "shell: bash" in block
        assert "playwright install" not in block
        assert "install_account_sync_browsers.sh" not in block
        assert "npm --prefix web ci" in block


@pytest.mark.parametrize("project", ["chromium", "ipad-webkit", "iphone-webkit"])
@pytest.mark.parametrize("shard", ["1/2", "2/2"])
def test_sync_shards_keep_project_and_one_worker(command_runner, project, shard):
    result, calls = command_runner([project, shard])
    assert result.returncode == 0
    assert calls == [
        f"--prefix web run test:sync -- --project={project} "
        f"--fully-parallel --workers=1 --shard={shard}"
    ]


@pytest.mark.parametrize("shard", ["", "0/2", "3/2", "1/3", "1/2; true"])
def test_invalid_sync_shard_never_runs_tests(command_runner, shard):
    result, calls = command_runner(["chromium", shard])
    assert result.returncode == 2
    assert calls == []


def test_local_shards_keep_auxiliary_tests_once_and_auth_separate():
    source = (ROOT / ".github/workflows/test.yml").read_text()
    block = source.split("  local-browser-tests:\n")[1].split("  local-browser:\n")[0]
    assert "suite: [local, acceptance, focused-ux, clipboard, auth]" in block
    assert "shard: [1]" in block
    for shard in [2, 3, 4]:
        assert f"- {{suite: local, shard: {shard}}}" in block
    assert "npm --prefix web run test:local -- --workers=2 --shard=${{ matrix.shard }}/4" in block
    assert block.count("if: matrix.suite == 'local' && matrix.shard == 1") == 2
    auth_step = block.split(
        "      - name: Verify auth, browser components and notification recovery\n"
    )[1].split("      - name:")[0]
    assert "if: matrix.suite == 'auth'" in auth_step
    for suite in ["auth", "sync-component", "notification", "unreleased"]:
        assert f"npm --prefix web run test:{suite}\n" in auth_step
        assert block.count(f"npm --prefix web run test:{suite}\n") == 1
    for output in [
        "autonavlog-sync-component-browser",
        "navmate-416-443-test-results",
        "navmate-543-browser",
    ]:
        assert f"/tmp/{output}" in block
    server_step = block.split(
        "      - name: Verify Local persistence and session/calculation "
        "regression without FastAPI\n"
    )[1].split("      - name:")[0]
    assert "if: matrix.suite != 'auth'" in server_step
    assert "if [ '${{ matrix.shard }}' = 1 ]; then" in block
    assert "production artifact rejects a different build manifest and recovers on reload" in block
    assert "name: local-browser-${{ matrix.suite }}-${{ matrix.shard }}-failure" in block


def test_migration_harness_is_only_started_for_contracts():
    source = (ROOT / ".github/workflows/test.yml").read_text()
    step = source.split(
        "      - name: Verify real SDK, Rules and cross-device Local-first workflows\n"
    )[1].split("      - name:")[0]
    guarded = step.split('if [ "$SUITE" = contracts ]; then\n')[1].split('          fi\n')[0]
    assert "python -m uvicorn migration_harness:app" in guarded
    assert "http://127.0.0.1:8186/healthz" in guarded
    assert step.count("python -m uvicorn migration_harness:app") == 1
    assert step.index("          fi\n") < step.index("npx --yes firebase-tools")

"""Shared validation runs once, while each shard remains fail-closed."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("scope", [None, "all", "pytest", "invalid"])
@pytest.mark.parametrize("failure", ["", "ruff", "python -m pytest", "python -m build"])
def test_check_scope_and_failures(tmp_path, scope, failure):
    calls = tmp_path / "calls"
    for command in ("python", "ruff", "mypy"):
        executable = tmp_path / command
        executable.write_text(
            '#!/bin/sh\n'
            'command="$(basename "$0") $*"\n'
            'echo "$command" >> "$CALLS"\n'
            'case "$command" in "$FAIL"*) [ -z "$FAIL" ] ;; *) exit 0 ;; esac\n'
        )
        executable.chmod(0o755)
    result = subprocess.run(
        ["sh", str(ROOT / "scripts/run_ci_checks.sh"), *([] if scope is None else [scope])],
        env={**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}",
             "CALLS": str(calls), "FAIL": failure},
        capture_output=True, text=True, timeout=5,
    )
    actual = calls.read_text().splitlines() if calls.exists() else []
    if scope == "invalid":
        assert result.returncode == 2
        assert actual == []
        return
    expected = [
        "python scripts/validate_release.py",
        "ruff check .",
        "mypy src/autonavlog",
        "python -m pytest -p scripts.pytest_shard --cov=autonavlog "
        "--cov-report=term-missing --durations=30",
        "python scripts/validate_performance_data.py data/performance",
        "python scripts/validate_runtime_data.py data",
        "python scripts/export_schemas.py --check",
        "python -m build",
    ]
    if scope == "pytest":
        expected = [expected[3]]
    failing = next((i for i, command in enumerate(expected)
                    if failure and command.startswith(failure)), None)
    assert result.returncode == (1 if failing is not None else 0)
    assert actual == (expected if failing is None else expected[:failing + 1])


def test_workflow_assigns_shared_checks_to_one_required_shard():
    workflow = (ROOT / ".github/workflows/test.yml").read_text()
    block = workflow.split("  pytest-tests:\n")[1].split("  pytest:\n")[0]
    assert "shard: [1, 2]" in block
    assert "- {shard: 1, checks: all}" in block
    assert "- {shard: 2, checks: pytest}" in block
    assert "autonavlog:test sh scripts/run_ci_checks.sh ${{ matrix.checks }}" in block
    assert "needs: [release-sources, pytest-tests]" in workflow

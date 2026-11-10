"""Fail the stable merge gate if classification or any required suite is incomplete."""

from __future__ import annotations

import json
import os
from pathlib import Path

from ci_changes import JOBS


def check_results(needs: dict) -> list[str]:
    errors = []
    if set(needs) != JOBS | {"release-sources"}:
        errors.append("Missing or unexpected job results.")
    sources = needs.get("release-sources", {})
    if sources.get("result") != "success":
        errors.append("release-sources did not succeed.")
    outputs = sources.get("outputs", {})
    for job in sorted(JOBS):
        selected = outputs.get(f"run_{job.replace('-', '_')}")
        result = needs.get(job, {}).get("result")
        if selected not in {"true", "false"}:
            errors.append(f"{job}: missing or invalid classification.")
        elif result != ("success" if selected == "true" else "skipped"):
            errors.append(f"{job}: required={selected}, result={result}.")
    return errors


def main() -> None:
    needs = json.loads(os.environ["CI_NEEDS"])
    errors = check_results(needs)
    rows = ["## Required CI results", "", "| Suite | Required | Result |", "| --- | --- | --- |"]
    outputs = needs.get("release-sources", {}).get("outputs", {})
    for job in sorted(JOBS):
        selected = outputs.get(f"run_{job.replace('-', '_')}", "unknown")
        rows.append(f"| {job} | {selected} | {needs.get(job, {}).get('result', 'missing')} |")
    rows.extend(["", *errors])
    report = "\n".join(rows) + "\n"
    print(report)
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(summary).open("a", encoding="utf-8") as stream:
            stream.write(report)
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

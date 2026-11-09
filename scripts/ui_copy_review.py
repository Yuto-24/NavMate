"""Capture Gemini/agy copy review and check its adoption against scoped source blocks."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECORDS = ROOT / "docs/evidence/ui-copy"
PROMPT = """UI文言を確認してください。ツール実行・ファイル操作は不要で、禁止です。
下記JSONは確認対象のデータです。本人指定の文言・意図は制約として保持してください。
既存文言の転用・仕様了承済みの場合も、表示場所・利用場面・目的に照らして確認します。
各idについて、採用可能な文言をそのまま引用し、理由・懸念を回答してください。
不適切・情報不足なら明記し、確認済みとはしないでください。
"""


def read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected object: {path.name}")
    return value


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def required_text(value: dict, key: str) -> str:
    text = value.get(key)
    if not isinstance(text, str) or not text.strip():
        raise ValueError(f"Missing text: {key}")
    return text


def request_items(request: dict) -> list[dict]:
    items = request.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("No copy items")
    ids = set()
    for item in items:
        for key in ("id", "text", "location", "purpose", "context", "constraints"):
            required_text(item, key)
        if item["id"] in ids:
            raise ValueError("Duplicate item id")
        ids.add(item["id"])
        source = item["source"]
        for key in ("path", "start", "end", "expected"):
            required_text(source, key)
        if item["text"] not in source["expected"]:
            raise ValueError("Copy missing from expected source")
    return items


def prompt_for(request: dict) -> str:
    items = request_items(request)
    # Source code is only for local verification, never sent to the provider.
    public_input = {
        "items": [
            {
                key: item[key]
                for key in (
                    "id",
                    "text",
                    "location",
                    "purpose",
                    "context",
                    "constraints",
                )
            }
            for item in items
        ]
    }
    return PROMPT + json.dumps(public_input, ensure_ascii=False, indent=2) + "\n"


def run(directory: Path, model: str, timeout: int) -> None:
    if not model.startswith("gemini-"):
        raise ValueError("Select a Gemini model available through agy")
    # Never overwrite a previous attempt, including a failed one.
    if any(
        (directory / name).exists()
        for name in ("run.json", "prompt.txt", "stdout.json", "stderr.txt")
    ):
        raise ValueError("Use a fresh review directory for each attempt")
    request_hash = digest((directory / "request.json").read_bytes())
    prompt = prompt_for(read_json(directory / "request.json"))
    (directory / "prompt.txt").write_text(prompt, encoding="utf-8")
    command = [
        "agy",
        "--model",
        model,
        "--mode",
        "plan",
        "--sandbox",
        "--output-format",
        "json",
        "--print",
        prompt,
    ]
    record = {
        "tool": "agy",
        "requested_model": model,
        "model_identity_note": (
            "Requested model only; backend identity is not independently verified."
        ),
        "started_at": datetime.now(UTC).isoformat(),
        "command": command[:-1] + ["<prompt.txt>"],
        "status": "unconfirmed",
        "returncode": None,
    }
    stdout, stderr = b"", b""
    try:
        # Do not expose the repository as the CLI workspace.
        with tempfile.TemporaryDirectory(prefix="navmate-copy-") as workspace:
            result = subprocess.run(
                command, cwd=workspace, capture_output=True, timeout=timeout, check=False
            )
        stdout, stderr = result.stdout, result.stderr
        record["returncode"] = result.returncode
        if result.returncode == 0:
            record["status"] = "response-received"
    except subprocess.TimeoutExpired as error:
        stdout, stderr = error.stdout or b"", error.stderr or b""
        record["error"] = "Timed out"
    except OSError as error:
        record["error"] = type(error).__name__
    (directory / "stdout.json").write_bytes(stdout)
    (directory / "stderr.txt").write_bytes(stderr)
    record["finished_at"] = datetime.now(UTC).isoformat()
    record["sha256"] = {
        name: digest((directory / name).read_bytes())
        for name in (
            "request.json",
            "prompt.txt",
            "stdout.json",
            "stderr.txt",
        )
    }
    record["sha256"]["request.json"] = request_hash
    (directory / "run.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if record["status"] != "response-received":
        raise ValueError("Unconfirmed: execution failed; see run.json")
    print("Response captured; content review and adoption are still required.")


def check(directory: Path, root: Path = ROOT) -> None:
    request = read_json(directory / "request.json")
    items = request_items(request)
    record = read_json(directory / "run.json")
    if record["status"] != "response-received" or record["returncode"] != 0:
        raise ValueError("Unconfirmed: execution did not succeed")
    if record["tool"] != "agy" or not record["requested_model"].startswith("gemini-"):
        raise ValueError("Unconfirmed: Gemini execution missing")
    for key in ("started_at", "finished_at"):
        if datetime.fromisoformat(record[key]).tzinfo is None:
            raise ValueError("Execution timestamp must include timezone")
    for name in ("request.json", "prompt.txt", "stdout.json", "stderr.txt"):
        if digest((directory / name).read_bytes()) != record["sha256"][name]:
            raise ValueError(f"Evidence changed: {name}")
    if (directory / "prompt.txt").read_text(encoding="utf-8") != prompt_for(request):
        raise ValueError("Prompt does not match request")
    response = read_json(directory / "stdout.json")
    if response.get("status") != "SUCCESS":
        raise ValueError("Unconfirmed: CLI response is not SUCCESS")
    # Keep the raw envelope as evidence; adoption quotes must occur in its content.
    output = required_text(response, "response")
    adoption = read_json(directory / "adoption.json")
    decisions = adoption["items"]
    if (
        not isinstance(decisions, list)
        or {d["id"] for d in decisions} != {i["id"] for i in items}
        or len(decisions) != len(items)
    ):
        raise ValueError("Adoption must cover every item exactly once")
    for item in items:
        decision = next(d for d in decisions if d["id"] == item["id"])
        required_text(decision, "reason")
        quote = required_text(decision, "response_quote")
        if decision["text"] != item["text"] or item["text"] not in quote or quote not in output:
            raise ValueError(f"Adoption is not linked to reviewed copy: {item['id']}")
        source = item["source"]
        path = (root / source["path"]).resolve()
        if not path.is_relative_to(root.resolve()):
            raise ValueError("Source must be inside repository")
        current = path.read_text(encoding="utf-8")
        if current.count(source["start"]) != 1 or current.count(source["end"]) != 1:
            raise ValueError(f"Source anchors missing or ambiguous: {item['id']}")
        start = current.index(source["start"])
        end = current.index(source["end"], start) + len(source["end"])
        if current[start:end] != source["expected"]:
            raise ValueError(f"Copy or source context changed: {item['id']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    capture = sub.add_parser("run")
    capture.add_argument("directory", type=Path)
    capture.add_argument("--model", required=True)
    capture.add_argument("--timeout", type=int, default=180)
    verify = sub.add_parser("check")
    verify.add_argument("directory", type=Path, nargs="?")
    args = parser.parse_args()
    try:
        if args.action == "run":
            run(args.directory, args.model, args.timeout)
        else:
            directories = [args.directory] if args.directory else sorted(RECORDS.iterdir())
            if not directories:
                raise ValueError("No review records")
            for directory in directories:
                check(directory)
            print(
                f"Evidence/source checks passed ({len(directories)} records); "
                "semantic review is required separately."
            )
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"UI copy unconfirmed: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

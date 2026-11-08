import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "ui_copy_review", Path(__file__).resolve().parents[2] / "scripts/ui_copy_review.py"
)
assert spec and spec.loader
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def prepared(tmp_path):
    directory = tmp_path / "review"
    directory.mkdir()
    source = '<aside name="MAP"><button onClick={paste}>Google Earth からペースト</button></aside>'
    (tmp_path / "view.tsx").write_text(source, encoding="utf-8")
    write_json(
        directory / "request.json",
        {
            "items": [
                {
                    "id": "paste",
                    "text": "Google Earth からペースト",
                    "location": "MAP",
                    "purpose": "クリップボード取込",
                    "context": "経路作成時",
                    "constraints": "本人指定",
                    "source": {
                        "path": "view.tsx",
                        "start": '<aside name="MAP">',
                        "end": "</aside>",
                        "expected": source,
                    },
                }
            ]
        },
    )
    return tmp_path, directory


def capture(monkeypatch, directory, *, code=0, response=None):
    if response is None:
        response = {"status": "SUCCESS", "response": "採用可能: Google Earth からペースト"}

    def execute(command, **kwargs):
        assert command[:3] == ["agy", "--model", "gemini-test"]
        assert kwargs["cwd"] != directory
        assert "onClick" not in command[-1]
        assert "view.tsx" not in command[-1]
        return subprocess.CompletedProcess(command, code, json.dumps(response).encode(), b"")

    monkeypatch.setattr(review.subprocess, "run", execute)
    review.run(directory, "gemini-test", 10)


def adopt(directory):
    write_json(
        directory / "adoption.json",
        {
            "items": [
                {
                    "id": "paste",
                    "text": "Google Earth からペースト",
                    "reason": "本人指定を保持。回答は採用可能と確認。",
                    "response_quote": "採用可能: Google Earth からペースト",
                }
            ]
        },
    )


def test_capture_adopt_and_check(monkeypatch, prepared):
    root, directory = prepared
    capture(monkeypatch, directory)
    adopt(directory)
    review.check(directory, root)
    with pytest.raises(ValueError, match="fresh review"):
        review.run(directory, "gemini-test", 10)


@pytest.mark.parametrize("failure", ["missing", "timeout", "exit", "bad_status", "empty"])
def test_unavailable_or_failed_execution_cannot_pass(monkeypatch, prepared, failure):
    root, directory = prepared
    if failure in ("missing", "timeout"):

        def execute(*args, **kwargs):
            if failure == "missing":
                raise FileNotFoundError("agy")
            raise subprocess.TimeoutExpired("agy", 10, output=b"partial")

        monkeypatch.setattr(review.subprocess, "run", execute)
        with pytest.raises(ValueError, match="execution failed"):
            review.run(directory, "gemini-test", 10)
    elif failure == "exit":
        with pytest.raises(ValueError, match="execution failed"):
            capture(monkeypatch, directory, code=1)
    else:
        capture(
            monkeypatch,
            directory,
            response={
                "status": "FAILED" if failure == "bad_status" else "SUCCESS",
                "response": "",
            },
        )
    adopt(directory)
    with pytest.raises(ValueError):
        review.check(directory, root)
    assert (directory / "run.json").exists()


@pytest.mark.parametrize("name", ["request.json", "prompt.txt", "stdout.json", "stderr.txt"])
def test_evidence_edits_or_loss_fail(monkeypatch, prepared, name):
    root, directory = prepared
    capture(monkeypatch, directory)
    adopt(directory)
    path = directory / name
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="Evidence changed"):
        review.check(directory, root)
    path.unlink()
    with pytest.raises(OSError):
        review.check(directory, root)


@pytest.mark.parametrize(
    "old,new",
    [
        ("Google Earth からペースト", "KMLを取り込む"),
        ("onClick={paste}", "onClick={choose}"),
        ('name="MAP"', 'name="Planning"'),
    ],
)
def test_integration_changes_to_copy_or_context_fail(monkeypatch, prepared, old, new):
    root, directory = prepared
    capture(monkeypatch, directory)
    adopt(directory)
    path = root / "view.tsx"
    path.write_text(path.read_text().replace(old, new))
    with pytest.raises(ValueError, match="Source anchors|source context"):
        review.check(directory, root)


def test_missing_or_unlinked_adoption_fails(monkeypatch, prepared):
    root, directory = prepared
    capture(monkeypatch, directory)
    with pytest.raises(OSError):
        review.check(directory, root)
    adopt(directory)
    decision = review.read_json(directory / "adoption.json")
    decision["items"][0]["response_quote"] = "Google Earth からペースト: invented approval"
    write_json(directory / "adoption.json", decision)
    with pytest.raises(ValueError, match="not linked"):
        review.check(directory, root)


def test_changed_input_during_execution_is_not_certified(monkeypatch, prepared):
    root, directory = prepared

    def execute(command, **kwargs):
        request = review.read_json(directory / "request.json")
        request["items"][0]["context"] = "changed after sending"
        write_json(directory / "request.json", request)
        return subprocess.CompletedProcess(command, 0, b'{"status":"SUCCESS"}', b"")

    monkeypatch.setattr(review.subprocess, "run", execute)
    review.run(directory, "gemini-test", 10)
    with pytest.raises(ValueError, match="Evidence changed"):
        review.check(directory, root)

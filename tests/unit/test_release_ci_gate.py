"""Release-only CI preflight: gate on the immutable tag's own push SHA."""

import base64

import pytest

from scripts.static_ops import release_ci_gate as gate, source_ci


REPO = {"full_name": "Yuto-24/NavMate"}
HEAD = "a" * 40
TAGGED = "b" * 40


def publisher_event():
    return {
        "repository": REPO, "action": "completed",
        "workflow_run": {
            "event": "push", "conclusion": "success", "path": gate.PUBLISHER,
            "head_branch": "main", "head_repository": REPO, "head_sha": HEAD,
        },
    }


def test_publisher_completion_selects_version_tag_not_latest_main():
    calls = []

    def get(path):
        calls.append(path)
        assert path == "contents/VERSION?ref=" + HEAD
        return {"type": "file", "encoding": "base64",
                "content": base64.b64encode(b"2.5.2\n").decode()}

    assert gate.release_tag(get, "workflow_run", publisher_event()) == "v2.5.2"
    assert calls == ["contents/VERSION?ref=" + HEAD]


@pytest.mark.parametrize("branch", ["main", "release/1.x", "release/2.x"])
def test_publisher_admits_supported_branches(branch):
    event = publisher_event()
    event["workflow_run"]["head_branch"] = branch
    assert gate.release_tag(
        lambda _: {"type": "file", "encoding": "base64",
                   "content": base64.b64encode(b"2.5.2\n").decode()},
        "workflow_run", event
    ) == "v2.5.2"


@pytest.mark.parametrize("change", ["repository", "path", "conclusion", "head_sha",
                                   "head_branch", "version"])
def test_invalid_publisher_completion_stops_before_wait(change):
    event = publisher_event()
    if change == "repository":
        event["repository"] = {"full_name": "other/NavMate"}
    elif change == "version":
        pass
    else:
        event["workflow_run"][change] = {
            "path": gate.source_ci.WORKFLOW, "conclusion": "failure",
            "head_sha": "invalid", "head_branch": "feature"
        }[change]

    def get(_):
        if change != "version":
            pytest.fail("Unexpected read")
        return {"type": "file", "encoding": "base64", "content": "bm90LWEtc2VtdmVy"}

    with pytest.raises(source_ci.Unavailable):
        gate.release_tag(get, "workflow_run", event)


def test_release_event_requires_stable_published_tag():
    event = {"repository": REPO, "action": "published",
             "release": {"tag_name": "v2.5.2", "draft": False, "prerelease": False}}
    assert gate.release_tag(lambda _: pytest.fail("Unexpected read"), "release", event) == "v2.5.2"
    for change, value in (("tag_name", "v2.5.2-rc1"), ("draft", True),
                          ("prerelease", True)):
        invalid = {"repository": REPO, "action": "published",
                   "release": {**event["release"], change: value}}
        with pytest.raises(source_ci.Unavailable):
            gate.release_tag(lambda _: pytest.fail("Unexpected read"), "release", invalid)


def test_resolves_annotated_tag_without_using_target_commitish():
    paths = []
    def get(path):
        paths.append(path)
        if path == "git/ref/tags/v2.5.2":
            return {"object": {"type": "tag", "sha": HEAD}}
        assert path == "git/tags/" + HEAD
        return {"object": {"type": "commit", "sha": TAGGED}}

    assert gate.release_commit(get, "v2.5.2") == TAGGED
    assert paths == ["git/ref/tags/v2.5.2", "git/tags/" + HEAD]


def test_waits_for_success_and_times_out_without_deploying(monkeypatch):
    now = [0]
    attempts = [0]

    def require_success(_, sha):
        assert sha == TAGGED
        attempts[0] += 1
        if attempts[0] < 3:
            raise source_ci.Unavailable("Not ready")
        return {"sha": sha, "run_id": 42, "run_attempt": 1}

    monkeypatch.setattr(gate.source_ci, "require_success", require_success)
    def tick():
        return now[0]

    def sleep(seconds):
        now[0] += seconds
    assert gate.await_source_ci(lambda _: None, TAGGED, timeout=30, interval=10,
                                monotonic=tick, sleep=sleep)["run_id"] == 42
    assert now == [20]
    monkeypatch.setattr(gate.source_ci, "require_success",
                        lambda *_: (_ for _ in ()).throw(source_ci.Unavailable("Pending")))
    now[0] = 0
    with pytest.raises(source_ci.Unavailable, match="timeout"):
        gate.await_source_ci(lambda _: None, TAGGED, timeout=10, interval=10,
                             monotonic=tick, sleep=sleep)
    assert now == [10]

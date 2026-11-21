"""Exercise publication/scheduling against real Git commits and HTTP responses."""

import fcntl
import functools
import json
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

from scripts.static_ops.local_runtime import (
    Settings,
    StaticHandler,
    Stopped,
    Superseded,
    Updater,
    healthy,
    load,
)


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def commit(repo):
    (repo / "input.txt").write_text(str(time.time_ns()))
    git(repo, "add", "input.txt")
    git(repo, "commit", "-qm", "candidate")
    return git(repo, "rev-parse", "HEAD")


def artifact(root, sha, *, expired=False):
    root.mkdir()
    (root / "index.html").write_text(sha * 1000)
    (root / "release.json").write_text(json.dumps({"commit": sha, "dirty": False}))
    feed = root / "weather/msm"
    feed.mkdir(parents=True)
    expiry = datetime.now(UTC) + timedelta(hours=-1 if expired else 6)
    (feed / "catalog.json").write_text(json.dumps({"expires_at": expiry.isoformat(),
                                                   "assets": [{"run": "20261103000000"}]}))
    return root


class ControlledUpdater(Updater):
    """Stub expensive build steps only; retain real scheduler, Git and pointer logic."""

    def __init__(self, settings):
        super().__init__(settings)
        self.calls = []
        self.fail = set()
        self.during_build = None
        self.weather_noop = False

    def source_validation(self, kind, sha, *, inventory=True):
        return None

    def build(self, kind, sha, source, job):
        self.calls.append((kind, sha))
        if (kind, sha) in self.fail:
            raise RuntimeError("Candidate rejected")
        if self.during_build:
            callback, self.during_build = self.during_build, None
            callback()
        if kind == "weather" and self.weather_noop:
            return None
        (self.s.state / "sources" / sha).mkdir(exist_ok=True)
        result = artifact(job / "artifact", sha)
        metadata = load(result / "release.json")
        metadata["configuration"] = self.configuration()
        (result / "release.json").write_text(json.dumps(metadata))
        return result


@pytest.fixture
def runtime(tmp_path):
    repo = tmp_path / "git/current"
    repo.mkdir(parents=True)
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "user.name", "Test")
    commit(repo)
    settings = Settings(repo, tmp_path / "state", tmp_path / "published")
    return ControlledUpdater(settings)


@pytest.mark.parametrize("failure", ["missing", "unavailable", "cancelled"])
def test_ci_wait_keeps_publication_and_active_sha_weather(runtime, monkeypatch, failure):
    from scripts.static_ops import source_ci

    now = time.time()
    runtime.tick(now)
    old = runtime.s.active()
    active_sha = load(old / "release.json")["commit"]
    new_sha = commit(runtime.s.source)

    def get(_client, _endpoint):
        if failure == "unavailable":
            raise OSError("outage")
        return {"workflow_runs": [] if failure == "missing" else [
            {"id": 1, "head_sha": new_sha, "event": "push", "status": "completed",
             "conclusion": "cancelled"}]}

    monkeypatch.setattr(source_ci.GitHub, "__call__", get)
    runtime.source_validation = Updater.source_validation.__get__(runtime)
    runtime.next_weather = 0
    runtime.tick(now + 1)
    # Weather publishes the old app with all local checks selected (no inventory).
    assert runtime.calls[-1] == ("weather", active_sha)
    assert runtime.source_inventory is None
    assert load(runtime.s.active() / "release.json")["commit"] == active_sha
    assert runtime.s.active("previous") == old
    assert runtime.status["failed_main_sha"] == new_sha
    assert ("main", new_sha) not in runtime.calls


def test_ci_revoked_before_main_pointer_switch_retains_current(runtime, monkeypatch):
    from scripts.static_ops import source_ci

    runtime.tick(time.time())
    old = runtime.s.active()
    new_sha = commit(runtime.s.source)
    runtime.next_weather = float("inf")

    def validate(kind, sha, *, inventory=True):
        if not inventory:
            raise source_ci.Unavailable("Source CI cancelled")
        return None

    runtime.source_validation = validate
    runtime.tick(time.time())
    assert ("main", new_sha) in runtime.calls
    assert runtime.s.active() == old
    assert runtime.status["failed_main_sha"] == new_sha


def test_main_change_noop_and_restart(runtime):
    now = time.time()
    first = runtime.desired()[0]
    runtime.tick(now)
    assert load(runtime.s.active() / "release.json")["commit"] == first
    runtime.weather_noop = True
    runtime.tick(now)
    runtime.tick(now)
    assert runtime.calls == [("main", first), ("weather", first)]
    second = commit(runtime.s.source)
    runtime.tick(now)
    assert load(runtime.s.active() / "release.json")["commit"] == second
    assert load(runtime.s.active("previous") / "release.json")["commit"] == first
    restarted = ControlledUpdater(runtime.s)
    restarted.weather_noop = True
    restarted.tick(now)
    assert restarted.calls == [("weather", second)]
    assert load(restarted.s.active() / "release.json")["commit"] == second


def test_failed_main_does_not_block_active_weather_or_change_pointer(runtime):
    now = time.time()
    runtime.tick(now)
    active = runtime.s.active()
    old = load(active / "release.json")["commit"]
    new = commit(runtime.s.source)
    runtime.weather_noop = True
    runtime.fail.add(("main", new))
    runtime.tick(now)
    assert runtime.s.active() == active
    assert runtime.status["failed_main_sha"] == new
    runtime.weather_noop = False
    runtime.next_weather = 0
    runtime.tick(now + 1)
    assert runtime.calls[-1] == ("weather", old)
    assert runtime.s.active() != active
    assert load(runtime.s.active() / "release.json")["commit"] == old
    assert runtime.calls.count(("main", new)) == 1
    runtime.fail.clear()
    runtime.tick(runtime.status["retry_main_at"] + 1)
    assert load(runtime.s.active() / "release.json")["commit"] == new


def test_superseded_commit_never_publishes(runtime):
    now = time.time()
    runtime.tick(now)
    original = runtime.s.active()
    commit(runtime.s.source)
    runtime.next_weather = now + 3600
    runtime.during_build = lambda: commit(runtime.s.source)
    runtime.tick(now)
    assert runtime.s.active() == original
    assert runtime.status["failed_main_sha"] is None
    newest = runtime.desired()[0]
    runtime.tick(now)
    assert load(runtime.s.active() / "release.json")["commit"] == newest


def test_weather_failure_retries_without_renewing_catalog(runtime):
    runtime.tick(time.time())
    active = runtime.s.active()
    before = (active / "weather/msm/catalog.json").read_bytes()
    sha = runtime.desired()[0]
    runtime.fail.add(("weather", sha))
    runtime.tick(time.time())
    assert runtime.s.active() == active
    assert (active / "weather/msm/catalog.json").read_bytes() == before
    assert runtime.next_weather > time.time() + 890


def test_atomic_http_publication_and_no_directory_or_private_access(runtime):
    runtime.tick(time.time())
    first = runtime.desired()[0]
    server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(
        StaticHandler, settings=runtime.s))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    seen = []

    def reader():
        for _ in range(25):
            with urlopen(base, timeout=3) as response:
                seen.append(response.read().decode())
                assert response.headers["Cache-Control"] == "no-cache"

    second = commit(runtime.s.source)
    runtime.next_weather = time.time() + 3600
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            responses = pool.submit(reader)
            runtime.tick(time.time())
            responses.result(timeout=10)
        with urlopen(base) as response:
            seen.append(response.read().decode())
        assert set(seen) <= {first * 1000, second * 1000}
        assert second * 1000 in seen
        for path in ("/weather/", "/status.json", "/api/session"):
            with pytest.raises(HTTPError) as error:
                urlopen(base + path)
            assert error.value.code == 404
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_health_separates_web_from_expired_forecast(runtime):
    runtime.tick(time.time())
    path = runtime.s.active() / "weather/msm/catalog.json"
    catalog = load(path)
    catalog["expires_at"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    path.write_text(json.dumps(catalog))
    assert not healthy(runtime.s, "health-updater")
    server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(
        StaticHandler, settings=runtime.s))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        assert healthy(replace(runtime.s, port=server.server_port), "health-web")
        with urlopen(f"http://127.0.0.1:{server.server_port}") as response:
            assert response.status == 200
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_job_timeout_terminates_process(runtime):
    runtime.deadline = time.monotonic() + 0.1
    runtime.env = {"PATH": "/usr/bin:/bin"}
    with pytest.raises(TimeoutError):
        runtime.run([sys.executable, "-c", "import time; time.sleep(30)"], runtime.s.state)


def test_gc_only_removes_generated_releases_and_sources(runtime):
    runtime.tick(time.time())
    unrelated = runtime.s.published / "releases/operator-backup"
    unrelated.mkdir()
    first = runtime.s.active()
    commit(runtime.s.source)
    runtime.next_weather = time.time() + 3600
    runtime.tick(time.time())
    commit(runtime.s.source)
    runtime.tick(time.time())
    assert not first.exists()
    assert unrelated.exists()
    assert len(list((runtime.s.state / "sources").iterdir())) == 2


def test_source_cannot_escape_git_volume(runtime, tmp_path):
    runtime.s.source.rename(tmp_path / "elsewhere")
    runtime.s.source.symlink_to(tmp_path / "elsewhere")
    with pytest.raises(ValueError, match="escaped"):
        runtime.desired()


def test_failed_jobs_keep_only_ten_generated_logs(runtime):
    sha = runtime.desired()[0]
    runtime.fail.add(("main", sha))
    unrelated = runtime.s.state / "logs/job-operator.log"
    unrelated.write_text("Keep operator evidence")
    for _ in range(12):
        assert not runtime.attempt("main", sha, runtime.s.source)
    assert len(list((runtime.s.state / "logs").glob("*.log"))) == 11
    assert unrelated.exists()


def test_clone_detached_worktree_is_independent(runtime, tmp_path):
    sha = runtime.desired()[0]
    worktree = runtime.s.source.parent / "detached"
    git(runtime.s.source, "worktree", "add", "--detach", str(worktree), sha)
    runtime.deadline = time.monotonic() + 10
    home = runtime.s.state / "work/clone-test/home"
    home.mkdir(parents=True)
    runtime.env = {"PATH": "/usr/bin:/bin", "HOME": str(home)}
    copy = tmp_path / "independent"
    runtime.clone(worktree, copy, sha)
    git(runtime.s.source, "worktree", "remove", str(worktree))
    assert git(copy, "rev-parse", "HEAD") == sha
    assert git(copy, "status", "--porcelain") == ""


def test_second_updater_cannot_start_a_concurrent_job(runtime):
    pending = cache_file(runtime, "raw/old/input.bin", age_days=8)
    with (runtime.s.state / "updater.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):
            runtime.serve()
    assert runtime.calls == []
    assert pending.exists()


def test_local_build_excludes_inherited_account_configuration(runtime, monkeypatch):
    for key in ("VITE_FIREBASE_API_KEY", "VITE_FIREBASE_AUTH_DOMAIN",
                "VITE_FIREBASE_PROJECT_ID", "VITE_FIREBASE_APP_ID",
                "VITE_LEGACY_MIGRATION_URL", "FIREBASE_ADMIN_TOKEN"):
        monkeypatch.setenv(key, "must-not-reach-local-build")
    monkeypatch.setenv("VITE_TAF_PROXY_URL", "https://weather.example/taf")
    assert runtime.configuration() == {"VITE_TAF_PROXY_URL": "https://weather.example/taf"}


def test_shared_build_requires_the_development_firebase_project(runtime, monkeypatch):
    monkeypatch.setenv("LOCAL_SHARED_PROJECTS", "1")
    monkeypatch.setenv("VITE_DEV_FIREBASE_PROJECT_ID", "navmate-prod")
    with pytest.raises(ValueError, match="NavMate-dev"):
        runtime.configuration()
    for key in ("VITE_DEV_FIREBASE_API_KEY", "VITE_DEV_FIREBASE_AUTH_DOMAIN",
                "VITE_DEV_FIREBASE_APP_ID"):
        monkeypatch.setenv(key, "dev-web-config")
    monkeypatch.setenv("VITE_DEV_FIREBASE_PROJECT_ID", "navmate-6b281")
    monkeypatch.setenv("VITE_LEGACY_MIGRATION_URL", "https://production.example")
    config = runtime.configuration()
    assert config["VITE_DEV_SHARED_PROJECTS"] == "1"
    assert config["VITE_DEV_FIREBASE_PROJECT_ID"] == "navmate-6b281"
    assert "VITE_LEGACY_MIGRATION_URL" not in config


def test_same_sha_configuration_switch_rebuilds_the_local_application(runtime, monkeypatch):
    now = time.time()
    runtime.tick(now)
    sha = runtime.desired()[0]
    runtime.weather_noop = True
    monkeypatch.setenv("VITE_TAF_PROXY_URL", "https://weather.example/taf")
    runtime.tick(now)
    assert runtime.calls == [("main", sha), ("weather", sha), ("main", sha)]
    assert load(runtime.s.active() / "release.json")["configuration"] == runtime.configuration()
    runtime.tick(now)
    assert len(runtime.calls) == 3


def cache_file(runtime, name, *, size=4, age_days=0):
    path = runtime.s.state / "cache/msm" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    modified = time.time() - age_days * 86400
    os.utime(path, (modified, modified))
    return path


def test_cache_retention_applies_age_then_one_combined_payload_budget(runtime, capsys):
    runtime.s = replace(runtime.s, msm_cache_max_bytes=9)
    expired = cache_file(runtime, "raw/expired/input.bin", age_days=8)
    oldest = cache_file(runtime, "raw/older/input.bin", size=3, age_days=3)
    normalized = cache_file(runtime, "normalized/run/forecast.nc", size=4, age_days=2)
    listing = cache_file(runtime, "listings/recent.html", size=5, age_days=1)
    lock = cache_file(runtime, "locks/input.lock", age_days=30)
    unrelated = cache_file(runtime, "operator-note.txt", age_days=30)
    runtime.collect()
    assert not expired.exists()
    assert not expired.parent.exists()
    assert not oldest.exists()
    assert normalized.exists() and listing.exists()
    assert lock.exists() and unrelated.exists()
    event = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert event["event"] == "msm_cache_collected"
    assert event["deleted_files"] == 2
    assert event["remaining_bytes"] == 9
    assert event["maximum_age_days"] == 7


def test_cache_collection_keeps_current_and_previous_publications(runtime):
    runtime.tick(time.time())
    commit(runtime.s.source)
    runtime.next_weather = time.time() + 3600
    runtime.tick(time.time())
    publications = [runtime.s.active(), runtime.s.active("previous")]
    for release in publications:
        (release / "weather/msm/retained.npz").write_bytes(b"published forecast")
    before = {file: file.read_bytes() for release in publications
              for file in release.rglob("*") if file.is_file()}
    expired = cache_file(runtime, "normalized/run/forecast.nc", age_days=8)
    runtime.collect()
    assert not expired.exists()
    assert [runtime.s.active(), runtime.s.active("previous")] == publications
    assert all(path.read_bytes() == value for path, value in before.items())


@pytest.mark.parametrize("link", ["cache", "cache/msm", "cache/msm/raw",
                                 "cache/msm/normalized/linked", "cache/msm/raw/linked.bin"])
def test_cache_collection_never_follows_symlinks(runtime, tmp_path, link):
    outside = tmp_path / "protected"
    outside.mkdir()
    protected = outside / "input.bin"
    protected.write_bytes(b"protected")
    os.utime(protected, (0, 0))
    path = runtime.s.state / link
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_dir():
        path.rmdir()
    path.symlink_to(protected if path.suffix == ".bin" else outside)
    runtime.collect_msm_cache()
    assert path.is_symlink()
    assert protected.read_bytes() == b"protected"


def test_cache_collection_leaves_special_files_untouched(runtime):
    pipe = runtime.s.state / "cache/msm/raw/operator-pipe"
    pipe.parent.mkdir(parents=True)
    os.mkfifo(pipe)
    runtime.collect_msm_cache()
    assert pipe.exists()


@pytest.mark.parametrize("outcome", ["success", "failure", "superseded", "stopped", "noop"])
def test_cache_collection_runs_before_and_after_every_job_outcome(runtime, outcome):
    runtime.tick(time.time())
    before = runtime.s.active()
    stale = cache_file(runtime, "raw/old/input.bin", age_days=8)
    produced = []

    def during_build():
        assert not stale.exists()
        produced.append(cache_file(runtime, "normalized/new/forecast.nc", age_days=8))
        assert produced[0].exists()
        if outcome == "failure":
            raise RuntimeError("Failed after populating cache")
        if outcome == "superseded":
            raise Superseded()
        if outcome == "stopped":
            raise Stopped()

    runtime.during_build = during_build
    runtime.weather_noop = outcome == "noop"
    sha = runtime.desired()[0]
    if outcome == "stopped":
        with pytest.raises(Stopped):
            runtime.attempt("weather", sha, runtime.s.source)
    else:
        assert runtime.attempt("weather", sha, runtime.s.source) is (outcome != "failure")
    assert not produced[0].exists()
    assert runtime.status["running"] is None
    if outcome != "success":
        assert runtime.s.active() == before


def test_startup_collects_before_first_update_under_writer_lock(runtime, monkeypatch):
    expired = cache_file(runtime, "raw/old/input.bin", age_days=8)

    def tick(_):
        assert not expired.exists()
        with (runtime.s.state / "updater.lock").open("a") as lock:
            with pytest.raises(BlockingIOError):
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        runtime.stop.set()

    monkeypatch.setattr(runtime, "tick", tick)
    monkeypatch.setattr("scripts.static_ops.local_runtime.signal.signal", lambda *_: None)
    runtime.serve()


def test_cache_delete_failure_is_reported_without_failing_publication(runtime, monkeypatch, capsys):
    expired = cache_file(runtime, "raw/old/input.bin", age_days=8)
    unlink = Path.unlink

    def denied(path, *args, **kwargs):
        if path == expired:
            raise PermissionError("Cache deletion denied")
        return unlink(path, *args, **kwargs)

    with monkeypatch.context() as scoped:
        scoped.setattr(Path, "unlink", denied)
        runtime.tick(time.time())
    assert runtime.s.active() is not None
    assert runtime.status["last_error"] is None
    assert runtime.status["running"] is None
    assert expired.exists()
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert any(item["event"] == "msm_cache_cleanup_failed" for item in events)
    runtime.collect_msm_cache()
    assert not expired.exists()


def test_cache_retention_defaults_and_environment_overrides(monkeypatch):
    monkeypatch.delenv("LOCAL_MSM_CACHE_MAX_BYTES", raising=False)
    monkeypatch.delenv("LOCAL_MSM_CACHE_MAX_AGE_DAYS", raising=False)
    default = Settings.environment()
    assert default.msm_cache_max_bytes == 20 * 1024**3
    assert default.msm_cache_max_age_days == 7
    monkeypatch.setenv("LOCAL_MSM_CACHE_MAX_BYTES", "1024")
    monkeypatch.setenv("LOCAL_MSM_CACHE_MAX_AGE_DAYS", "2")
    configured = Settings.environment()
    assert configured.msm_cache_max_bytes == 1024
    assert configured.msm_cache_max_age_days == 2


@pytest.mark.parametrize("key", ["LOCAL_MSM_CACHE_MAX_BYTES", "LOCAL_MSM_CACHE_MAX_AGE_DAYS"])
@pytest.mark.parametrize("value", ["0", "-1", "invalid"])
def test_cache_retention_rejects_unbounded_or_invalid_settings(monkeypatch, key, value):
    monkeypatch.setenv(key, value)
    with pytest.raises(ValueError):
        Settings.environment()

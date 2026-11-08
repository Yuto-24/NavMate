"""Real HTTP + SQLite tests for the opt-in shared development workspace."""
import functools
import json
import threading
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from scripts.static_ops.dev_projects import API, MARKER, MAX_BODY, SharedProjects
from scripts.static_ops.local_runtime import Settings, StaticHandler


def record(id="one", token="t1", *, saved=True):
    draft = {"id": id, "name": id, "revision": 1, "status": "DRAFT"}
    return dict(schemaVersion=2, id=id, token=token, draft=draft,
                checkpoint=draft if saved else None, lastCalculation={"outcome": {"retained": True}},
                updatedAt="2026-11-08T00:00:00Z")


@contextmanager
def serve(tmp_path, enabled=True):
    published = tmp_path / "published"
    release = published / "releases" / ("r-" + "a" * 32)
    release.mkdir(parents=True, exist_ok=True)
    (release / "index.html").write_text("<html><head></head><body>app</body></html>")
    if not (published / "current").exists():
        (published / "current").symlink_to(release)
    settings = Settings(tmp_path / "source", tmp_path / "state", published)
    server = ThreadingHTTPServer(("127.0.0.1", 0), StaticHandler)
    origin = f"http://127.0.0.1:{server.server_port}"
    projects = SharedProjects(tmp_path / "private/projects.sqlite3", {origin}) if enabled else None
    server.RequestHandlerClass = functools.partial(StaticHandler, settings=settings, projects=projects)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield origin
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def request(origin, action=None, data=None, *, headers=None, path=None, method=None):
    hdr = {"X-NavMate-Dev-Storage": "1", "Content-Type": "application/json", **(headers or {})}
    req = Request(origin + (path if path is not None else API + ("/" + action if action else "")),
                  data=json.dumps(data).encode() if data is not None else None, headers=hdr, method=method)
    try:
        response = urlopen(req, timeout=3)
    except HTTPError as error:
        response = error
    with response:
        body = response.read()
        return response.status, body


def write(origin, value, expected=None, replace=False):
    return request(origin, "write", {"record": value, "expectedToken": expected, "replaceLatest": replace})


def rows(origin):
    status, body = request(origin)
    assert status == 200
    return json.loads(body)["records"]


def test_two_clients_read_edit_delete_and_restart_retains_navlog(tmp_path):
    original = record()
    with serve(tmp_path) as origin:
        assert write(origin, original)[0] == 200
        assert rows(origin) == [original]  # second HTTP client sees the same record
        updated = record(token="t2")
        updated["draft"]["name"] = "edited on Android"
        assert write(origin, updated, "t1")[0] == 200
        assert write(origin, record(token="stale"), "t1")[0] == 409
        assert rows(origin) == [updated]
    with serve(tmp_path) as origin:
        assert rows(origin) == [updated]
        assert request(origin, "delete", {"id": "one", "expectedToken": "t1"})[0] == 409
        assert request(origin, "delete", {"id": "one", "expectedToken": "t2"})[0] == 200
        assert rows(origin) == []


def test_latest_open_and_failed_replacement_are_atomic(tmp_path):
    with serve(tmp_path) as origin:
        saved, latest = record(), record("latest", saved=False)
        assert write(origin, saved)[0] == 200
        assert write(origin, latest, replace=True)[0] == 200
        assert write(origin, record("new", saved=False), "missing", True)[0] == 409
        assert len(rows(origin)) == 2
        assert request(origin, "open", {"record": saved, "expectedToken": "wrong"})[0] == 409
        assert len(rows(origin)) == 2
        opened = {**saved, "token": "restored-checkpoint"}
        assert request(origin, "open", {"record": opened, "expectedToken": saved["token"]})[0] == 200
        assert rows(origin) == [opened]
        assert write(origin, opened, saved["token"])[0] == 200  # retry lost acknowledgement, no extra deletion


def test_anonymous_import_is_insert_only_and_never_resurrects_deleted_copy(tmp_path):
    with serve(tmp_path) as origin:
        original = record()
        imported = {"source": "browser-one", "record": original}
        assert request(origin, "import", imported) == (200, b'{"conflict": false}')
        assert request(origin, "delete", {"id": "one", "expectedToken": "t1"})[0] == 200
        assert request(origin, "import", imported)[0] == 200
        assert rows(origin) == []
        updated = record(token="remote")
        assert write(origin, updated)[0] == 200
        status, body = request(origin, "import", {"source": "browser-two", "record": original})
        assert status == 200 and json.loads(body)["conflict"] is True
        assert rows(origin) == [updated]


def test_disabled_api_and_marker_do_not_change_default_runtime(tmp_path):
    with serve(tmp_path, enabled=False) as origin:
        assert request(origin)[0] == 404
        assert write(origin, record())[0] == 404
        assert MARKER not in request(origin, path="/")[1]
    with serve(tmp_path) as origin:
        assert MARKER in request(origin, path="/")[1]
        assert MARKER in request(origin, path="/index.html")[1]
        assert request(origin, path="/", method="HEAD")[1] == b""
        assert request(origin, path="/projects.sqlite3")[0] == 404
        assert MARKER not in (tmp_path / "published/current/index.html").read_bytes()


@pytest.mark.parametrize("headers", [
    {"X-NavMate-Dev-Storage": ""}, {"Origin": "https://other.example"},
    {"Sec-Fetch-Site": "cross-site"}, {"Host": "rebound.example"},
])
def test_same_origin_boundary_rejects_cross_site_read_and_write(tmp_path, headers):
    with serve(tmp_path) as origin:
        assert request(origin, headers=headers)[0] == 403
        assert request(origin, "delete", {"id": "one"}, headers=headers)[0] == 403
        assert rows(origin) == []


def test_invalid_record_and_oversized_body_preserve_data(tmp_path):
    with serve(tmp_path) as origin:
        original = record()
        assert write(origin, original)[0] == 200
        invalid = record(token="invalid")
        invalid["draft"]["id"] = "different"
        assert write(origin, invalid, "t1")[0] == 400
        assert request(origin, "write", {}, headers={"Content-Length": str(MAX_BODY + 1)})[0] == 413
        assert request(origin, "write", {}, headers={"Content-Type": "text/plain"})[0] == 400
        assert rows(origin) == [original]

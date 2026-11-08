"""Opt-in, unauthenticated shared Projects for the local development runtime only."""
from __future__ import annotations

import io
import json
import sqlite3
from contextlib import closing
from http.server import SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlsplit

API = "/api/dev-projects"
MAX_BODY = 10 * 1024 * 1024
MARKER = b'<meta name="navmate-dev-shared-projects" content="1">'


class ProjectError(Exception):
    def __init__(self, status: int, code: str):
        self.status, self.code = status, code


def identifier(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 128:
        raise ProjectError(400, "INVALID")
    return value


def record_payload(record):
    """Validate the storage envelope; the existing browser domain validator owns Project semantics."""
    if not isinstance(record, dict) or record.get("schemaVersion") != 2:
        raise ProjectError(400, "INVALID")
    identifier(record.get("id"))
    identifier(record.get("token"))
    identifier(record.get("updatedAt"))
    if set(record) != {"schemaVersion", "id", "token", "checkpoint", "draft", "lastCalculation", "updatedAt"}:
        raise ProjectError(400, "INVALID")
    for key in ("draft", "checkpoint"):
        project = record[key]
        if key == "checkpoint" and project is None:
            continue
        if not isinstance(project, dict) or project.get("id") != record["id"]:
            raise ProjectError(400, "INVALID")
    return json.dumps(record, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


class SharedProjects:
    def __init__(self, path: Path, origins: set[str]):
        self.path, self.origins = path, origins
        self.hosts = {urlsplit(origin).netloc for origin in origins}
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS projects (id TEXT PRIMARY KEY, token TEXT NOT NULL, payload TEXT NOT NULL)")
            # Remember copied originals even after their shared copy is deleted.
            db.execute("CREATE TABLE IF NOT EXISTS imports (source TEXT, id TEXT, conflict INTEGER NOT NULL, PRIMARY KEY(source,id))")

    def list(self):
        with closing(sqlite3.connect(self.path)) as db:
            return [json.loads(row[0]) for row in db.execute("SELECT payload FROM projects ORDER BY id")]

    def mutate(self, action, body):
        if not isinstance(body, dict):
            raise ProjectError(400, "INVALID")
        record = body.get("record")
        payload = record_payload(record) if action in ("write", "open", "import") else None
        project_id = record["id"] if payload else identifier(body.get("id"))
        with closing(sqlite3.connect(self.path, timeout=5)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT token, payload FROM projects WHERE id=?", (project_id,)).fetchone()
            if action == "import":
                source = identifier(body.get("source"))
                previous = db.execute("SELECT conflict FROM imports WHERE source=? AND id=?", (source, project_id)).fetchone()
                if previous is not None:
                    return {"conflict": bool(previous[0])}
                conflict = row is not None and row[0] != record["token"]
                if row is None:
                    db.execute("INSERT INTO projects VALUES (?,?,?)", (project_id, record["token"], payload))
                db.execute("INSERT INTO imports VALUES (?,?,?)", (source, project_id, int(conflict)))
                return {"conflict": conflict}
            expected = body.get("expectedToken")
            if expected is not None:
                identifier(expected)
            if (row[0] if row else None) != expected:
                # An identical write can be retried after an acknowledgement was lost.
                if action == "write" and row and row[1] == payload:
                    return {}
                raise ProjectError(409, "CONFLICT")
            if action == "delete":
                db.execute("DELETE FROM projects WHERE id=?", (project_id,))
                return {}
            if action == "open" and row is None:
                raise ProjectError(409, "CONFLICT")
            if action not in ("write", "open"):
                raise ProjectError(404, "NOT_FOUND")
            if action == "write" and type(body.get("replaceLatest")) is not bool:
                raise ProjectError(400, "INVALID")
            db.execute("INSERT OR REPLACE INTO projects VALUES (?,?,?)", (project_id, record["token"], payload))
            if action == "open" or body.get("replaceLatest"):
                # This dev instance is one shared workspace with one Latest slot.
                for other_id, other_payload in db.execute("SELECT id,payload FROM projects WHERE id != ?", (project_id,)).fetchall():
                    if json.loads(other_payload)["checkpoint"] is None:
                        db.execute("DELETE FROM projects WHERE id=?", (other_id,))
            return {}


class DevProjectsHandler(SimpleHTTPRequestHandler):
    projects: SharedProjects | None = None

    def json_response(self, status, value):
        data = json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def check_project_request(self):
        # This is a same-origin boundary, not authentication. Direct clients are allowed.
        if not self.projects:
            raise ProjectError(404, "NOT_FOUND")
        if (self.headers.get("Host") not in self.projects.hosts
                or self.headers.get("X-NavMate-Dev-Storage") != "1"
                or self.headers.get("Sec-Fetch-Site") == "cross-site"
                or (self.headers.get("Origin") is not None
                    and self.headers["Origin"] not in self.projects.origins)):
            raise ProjectError(403, "FORBIDDEN")

    def project_request(self, action=None):
        try:
            self.check_project_request()
            if action is None:
                self.json_response(200, {"records": self.projects.list()})
                return
            if action not in ("write", "open", "delete", "import"):
                raise ProjectError(404, "NOT_FOUND")
            if self.headers.get_content_type() != "application/json" or self.headers.get("Transfer-Encoding"):
                raise ProjectError(400, "INVALID")
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_BODY:
                raise ProjectError(413, "INVALID")
            self.connection.settimeout(10)
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ProjectError(400, "INVALID")
            body = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            self.json_response(200, self.projects.mutate(action, body))
        except ProjectError as error:
            self.json_response(error.status, {"error": error.code})
        except (ValueError, UnicodeError, RecursionError):
            self.json_response(400, {"error": "INVALID"})
        except (OSError, sqlite3.Error):
            self.json_response(503, {"error": "UNAVAILABLE"})

    def do_POST(self):
        path = urlsplit(self.path).path
        if path.startswith(API + "/"):
            self.project_request(path[len(API) + 1:])
        else:
            self.send_error(404)

    def send_head(self):
        # Only the local runtime injects this marker. Published artifacts remain unchanged.
        if self.projects and urlsplit(self.path).path in ("/", "/index.html"):
            path = Path(self.translate_path("/index.html"))
            if not path.is_file():
                return super().send_head()
            data = path.read_bytes().replace(b"</head>", MARKER + b"</head>", 1)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            return io.BytesIO(data)
        return super().send_head()

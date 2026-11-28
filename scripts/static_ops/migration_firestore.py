"""Bounded Firestore REST transport; no credential reaches candidate subprocesses."""

from __future__ import annotations

import contextlib
import json
import re
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

from scripts.static_ops import app_release as app

MAX_DOCUMENT = 900 * 1024
MAX_RESPONSE = 12 * 1024 * 1024
ISOLATION_PROJECTS = ("navmate-prod", "navmate-6b281")
ISOLATION_DOCUMENT = "_navmate_acceptance/migration_evidence_isolation_v1"
ISOLATION_ERROR_LIMIT = 8192


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def is_read_denial(error):
    if error.code != 403:
        return False
    try:
        raw = error.read(ISOLATION_ERROR_LIMIT + 1)
        if len(raw) > ISOLATION_ERROR_LIMIT:
            return False
        payload = json.loads(raw)
        info = payload.get("error") if isinstance(payload, dict) else None
    except (ValueError, OSError):
        return False
    if not isinstance(info, dict) or info.get("status") != "PERMISSION_DENIED":
        return False
    message = info.get("message")
    return message == "Missing or insufficient permissions." or (
        isinstance(message, str)
        and message.startswith("Permission 'datastore.entities.get' denied ")
    )


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False)


def display(value, depth=0):
    """Firestore cannot nest arrays in arrays. Index maps retain expandable JSON order."""
    app.require(depth <= 18, "Review display nesting limit exceeded")
    if isinstance(value, dict):
        return {key: display(item, depth + 1) for key, item in value.items()}
    if isinstance(value, list):
        return {f"[{index:06d}]": display(item, depth + 1)
                for index, item in enumerate(value)}
    return value


def encode(value):
    if value is None:
        return {"nullValue": None}
    if isinstance(value, bool):
        return {"booleanValue": value}
    if isinstance(value, int):
        app.require(-(2**63) <= value < 2**63, "Review integer out of range")
        return {"integerValue": str(value)}
    if isinstance(value, float):
        return {"doubleValue": value}
    if isinstance(value, str):
        return {"stringValue": value}
    app.require(isinstance(value, dict), "Unsupported review field")
    return {"mapValue": {"fields": {key: encode(item) for key, item in value.items()}}}


def decode(value):
    if "mapValue" in value:
        return {key: decode(item) for key, item in value["mapValue"].get("fields", {}).items()}
    if "integerValue" in value:
        return int(value["integerValue"])
    if "doubleValue" in value:
        return float(value["doubleValue"])
    for kind in ("nullValue", "booleanValue", "stringValue"):
        if kind in value:
            return value[kind]
    raise app.Blocked("Unsupported review field")


def same(left, right):
    """Compare JSON values recursively without bool/int/float coercion."""
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(same(left[key], right[key]) for key in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(same(a, b) for a, b in zip(left, right, strict=True))
    return left == right


class Firestore:
    def __init__(self, project, credentials_file=None, service_account=None, *, emulator=None):
        app.require(re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]", project),
                    "Dedicated evidence project required")
        self.project = project
        self.root = f"projects/{project}/databases/(default)/documents"
        self.credentials = None
        if emulator:
            # Explicit test injection only; Actions never consumes emulator environment variables.
            app.require(project.startswith("demo-") and re.fullmatch(r"127\.0\.0\.1:\d+", emulator),
                        "Loopback demo emulator required")
            self.base = "http://" + emulator + "/v1/" + self.root
        else:
            from google.auth.identity_pool import Credentials

            app.require(service_account and re.fullmatch(
                r"[a-z][a-z0-9-]{4,28}[a-z0-9]@" + re.escape(project)
                + r"\.iam\.gserviceaccount\.com", service_account),
                "Dedicated evidence service account required")
            info = json.loads(Path(credentials_file).read_text())
            app.require(info.get("type") == "external_account" and info.get(
                "service_account_impersonation_url") ==
                "https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/"
                + service_account + ":generateAccessToken", "Evidence WIF identity mismatch")
            self.credentials = Credentials.from_info(
                info, scopes=["https://www.googleapis.com/auth/datastore"])
            self.base = "https://firestore.googleapis.com/v1/" + self.root

    def authorization(self):
        if self.credentials is None:
            return "Bearer owner"

        from google.auth.transport.requests import Request as AuthRequest

        # Refresh before expiration even after a long build; scopes belong only to evidence SA.
        if not self.credentials.valid:
            auth = AuthRequest()
            try:
                self.credentials.refresh(lambda **kw: auth(**{**kw, "timeout": 30}))
            finally:
                auth.session.close()
        app.require(self.credentials.valid, "Evidence authentication unavailable")
        return "Bearer " + self.credentials.token

    def verify_isolation(self):
        """Read only the known synthetic marker; never consume a successful response."""
        app.require(self.credentials is not None, "Evidence service account required")
        opener = build_opener(NoRedirect())
        for project in ISOLATION_PROJECTS:
            url = (f"https://firestore.googleapis.com/v1/projects/{project}"
                   "/databases/(default)/documents/" + ISOLATION_DOCUMENT
                   + "?mask.fieldPaths=synthetic_only")
            request = Request(url, method="GET", headers={"Authorization": self.authorization()})
            try:
                with opener.open(request, timeout=30):
                    raise app.Blocked(f"Evidence isolation failed for {project}: read was allowed")
            except HTTPError as error:
                with error:
                    message = f"Evidence isolation inconclusive for {project} (HTTP {error.code})"
                    app.require(is_read_denial(error), message)
            except (URLError, OSError):
                raise app.Blocked(f"Evidence isolation unavailable for {project}") from None

    def request(self, path, body=None, *, method="POST", missing=False):
        headers = {"Content-Type": "application/json", "Authorization": self.authorization()}
        request = Request(self.base + path, method=method, headers=headers,
                          data=canonical(body).encode() if body is not None else None)
        try:
            with urlopen(request, timeout=30) as response:
                raw = response.read(MAX_RESPONSE + 1)
                app.require(len(raw) <= MAX_RESPONSE, "Evidence response too large")
                return json.loads(raw)
        except HTTPError as error:
            if missing and error.code == 404:
                return None
            raise app.Blocked("Evidence API request failed") from None

    @contextlib.contextmanager
    def transaction(self, *, write=False):
        mode = {"readWrite": {}} if write else {"readOnly": {}}
        token = self.request(":beginTransaction", {"options": mode})["transaction"]
        try:
            yield token
        finally:
            try:
                self.request(":rollback", {"transaction": token})
            except Exception:
                pass  # Read-only snapshot release cannot authorize a write.

    def get(self, path, transaction=None):
        if transaction:
            rows = self.request(":batchGet", {
                "documents": [self.root + "/" + path], "transaction": transaction})
            app.require(isinstance(rows, list) and len(rows) == 1,
                        "Evidence read response incomplete")
            row = rows[0]
            app.require(row.get("missing", row.get("found", {}).get("name"))
                        == self.root + "/" + path, "Evidence identity changed")
            result = row.get("found")
        else:
            result = self.request("/" + path, method="GET", missing=True)
        if result is None:
            return None
        app.require(result.get("name") == self.root + "/" + path, "Evidence identity changed")
        return {key: decode(item) for key, item in result.get("fields", {}).items()}

    def put(self, path, value, *, create=True):
        # Wire JSON is a conservative upper bound on stored document size, including its name.
        document = {"name": self.root + "/" + path,
                    "fields": {key: encode(item) for key, item in value.items()}}
        app.require(len(canonical(document).encode()) + 1024 <= MAX_DOCUMENT,
                    "Evidence document exceeds 900 KiB")
        return {"update": document, **({"currentDocument": {"exists": False}} if create else {})}

    def commit(self, writes, transaction=None):
        self.request(":commit", {"writes": writes,
                                **({"transaction": transaction} if transaction else {})})

    def groups(self):
        token, seen = "", set()
        for _ in range(100):
            suffix = "?pageSize=100" + ("&pageToken=" + quote(token, safe="") if token else "")
            result = self.request("/migrationGroups" + suffix, method="GET")
            for item in result.get("documents", []):
                name = item["name"].removeprefix(self.root + "/")
                app.require(name.startswith("migrationGroups/") and name not in seen,
                            "Evidence group inventory changed")
                seen.add(name)
                yield name.split("/")[1]
            token = result.get("nextPageToken", "")
            if not token:
                return
        raise app.Blocked("Evidence retention inventory limit exceeded")


def configured(env, *, allow_disabled=False):
    project = env.get("STATIC_MIGRATION_EVIDENCE_PROJECT_ID", "")
    application = env.get("VITE_FIREBASE_PROJECT_ID", "")
    app.require(re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]", application),
                "Known application project required for evidence isolation")
    app.require(project not in ("navmate-6b281", application),
                "Evidence must be separate from application data")
    app.require(allow_disabled or env.get("STATIC_MIGRATION_EVIDENCE_ENABLED") == "true",
                "Evidence path awaits synthetic live acceptance")
    return Firestore(project, env.get("STATIC_MIGRATION_EVIDENCE_CREDENTIALS_FILE"),
                     env.get("STATIC_MIGRATION_EVIDENCE_SERVICE_ACCOUNT"))

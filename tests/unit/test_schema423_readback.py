"""Fail-closed, provider-free checks for the one-time Issue #423 readback."""

from __future__ import annotations

from scripts.static_ops import app_release as app
from scripts.static_ops import schema423_readback as check



ENV = {
    "STATIC_APPROVED_SHA": check.CURRENT,
    "VITE_FIREBASE_PROJECT_ID": check.PROJECT,
    "CLOUDFLARE_ACCOUNT_ID": "a" * 32,
    "CLOUDFLARE_API_TOKEN": "CLOUDFLARE_SECRET",
    "STATIC_GOOGLE_ACCESS_TOKEN": "GOOGLE_SECRET",
}
RULES = "rules_version = '2';\n"
RULES_HASH = app.digest(RULES.encode())
RULES_BLOB = "a" * 40


class Provider:
    def __init__(self):
        self.pages_commit = check.CURRENT
        self.rules_source = RULES
        self.tag = check.CANDIDATE
        self.release_reads = 0
        self.actions: list[str] = []

    def git(self, *args):
        self.actions.append("git")
        if args[0] == "rev-parse":
            return self.tag
        if args[:2] == ("merge-base", "--is-ancestor"):
            return ""
        raise AssertionError("unexpected git command")

    def source_digest(self, sha, path):
        self.actions.append("source_digest")
        assert sha in (check.CURRENT, check.CANDIDATE)
        return RULES_BLOB if path == check.RULES_PATH else "indexes-blob"

    def rules_source(self, sha):
        self.actions.append("rules_source")
        assert sha == check.CANDIDATE
        return RULES

    def target(self, variables):
        self.actions.append("target")
        assert variables == {"CLOUDFLARE_ACCOUNT_ID": "a" * 32}
        return {
            "id": "pages-deployment",
            "commit": self.pages_commit,
            "project_digest": "project-configuration-digest",
        }

    def rules_get(self, path):
        self.actions.append("rules_get")
        release = f"projects/{check.PROJECT}/releases/cloud.firestore"
        ruleset = f"projects/{check.PROJECT}/rulesets/validated-123"
        if path == release:
            self.release_reads += 1
            return {
                "rulesetName": ruleset,
                "updateTime": "2026-11-11T00:00:00Z"
                if self.release_reads == 1 else getattr(self, "final_time", "2026-11-11T00:00:00Z"),
            }
        assert path == ruleset
        return {
            "source": {"files": [{"name": check.RULES_PATH, "content": self.rules_source}]}
        }


def canonical(_origin, sha):
    assert sha == check.CURRENT
    return {"version": "2.2.2"}


def test_readback_observes_canonical_pages_and_rules_without_mutation():
    provider = Provider()
    result = check.observe(provider, ENV, canonical_reader=canonical)
    assert result["status"] == "MATCH"
    assert result["current_sha"] == check.CURRENT
    assert result["candidate_sha"] == check.CANDIDATE
    assert result["live_rules_source_sha256"] == RULES_HASH
    assert provider.actions.count("rules_get") == 3
    assert set(provider.actions) == {"git", "source_digest", "rules_source", "target", "rules_get"}
    assert "CLOUDFLARE_SECRET" not in str(result)
    assert "GOOGLE_SECRET" not in str(result)


def test_missing_authentication_fails_before_network():
    provider = Provider()
    variables = {**ENV, "STATIC_GOOGLE_ACCESS_TOKEN": ""}
    try:
        check.observe(provider, variables, canonical_reader=canonical)
    except check.ReadbackBlocked as error:
        assert str(error) == "credentials"
    else:
        raise AssertionError("missing authentication accepted")
    assert not provider.actions


def test_changed_approved_sha_fails_before_network():
    provider = Provider()
    try:
        check.observe(
            provider, {**ENV, "STATIC_APPROVED_SHA": "b" * 40}, canonical_reader=canonical
        )
    except check.ReadbackBlocked as error:
        assert str(error) == "scope"
    else:
        raise AssertionError("changed approved SHA accepted")
    assert not provider.actions


def test_mismatched_tag_or_rules_cannot_pass():
    for changed in ("tag", "rules_source"):
        provider = Provider()
        if changed == "tag":
            provider.tag = "b" * 40
        else:
            provider.rules_source = "different"
        try:
            check.observe(provider, ENV, canonical_reader=canonical)
        except check.ReadbackBlocked as error:
            assert str(error) in ("source", "live_rules")
        else:
            raise AssertionError(f"{changed} mismatch accepted")


def test_changed_pages_deployment_or_rules_release_cannot_pass():
    for changed in ("pages", "rules"):
        provider = Provider()
        if changed == "pages":
            provider.pages_commit = "b" * 40
        else:
            provider.final_time = "2026-11-11T00:00:01Z"
        try:
            check.observe(provider, ENV, canonical_reader=canonical)
        except check.ReadbackBlocked as error:
            assert str(error) in ("pages_identity", "live_rules")
        else:
            raise AssertionError(f"{changed} drift accepted")


def test_wrong_canonical_version_stops_before_provider_reads():
    provider = Provider()
    try:
        check.observe(
            provider, ENV, canonical_reader=lambda *_: {"version": "2.3.0"}
        )
    except check.ReadbackBlocked as error:
        assert str(error) == "canonical_identity"
    else:
        raise AssertionError("wrong canonical version accepted")
    assert "target" not in provider.actions
    assert "rules_get" not in provider.actions

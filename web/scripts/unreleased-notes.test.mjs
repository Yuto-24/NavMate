import { execFileSync } from "node:child_process";
import { mkdtempSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import assert from "node:assert/strict";
import { collectUnreleased, localUnreleased, pendingNotes } from "./unreleased-notes.mjs";

const head = "a".repeat(40), base = "b".repeat(40), merged = "c".repeat(40);
const later = "d".repeat(40), otherLine = "e".repeat(40);
const release = (tag_name, extra = {}) => ({ tag_name, draft: false, prerelease: false, ...extra });
const pull = (number, merge_commit_sha = merged, notes = "- A pending change") => ({
  number, title: `Change ${number}`, merge_commit_sha, merged_at: "2026-11-27T00:00:00Z",
  body: `## Pending release notes\n\n${notes}\n\n## Other section\nnot a note`,
});
function fixture({ releases = [release("v2.6.0")], commits = [merged], prs = [pull(543)], requestHook } = {}) {
  const calls = [];
  const request = async path => {
    calls.push(path);
    const hooked = requestHook?.(path);
    if (hooked !== undefined) return hooked;
    if (path.startsWith("/releases?")) return releases;
    if (path.startsWith("/compare/")) return { status: "ahead", base_commit: { sha: base },
      total_commits: commits.length, commits: commits.map(sha => ({ sha })) };
    if (path.startsWith("/pulls?")) return prs;
    throw new Error(`Unexpected request ${path}`);
  };
  return { calls, run: () => collectUnreleased({ head, version: "2.6.0", request }) };
}

test("only merged PRs included in the running build contribute pending notes", async () => {
  const { run } = fixture({ prs: [pull(543), pull(544, later), pull(12, otherLine),
    { ...pull(545), merged_at: null }, pull(546, merged, "None"),
    { ...pull(547), body: "  Release: required  \r\n" }] });
  assert.deepEqual(await run(), { status: "ready", head,
    baseline: { version: "2.6.0", commit: base },
    entries: [{ number: 543, title: "Change 543", notes: "- A pending change" }] });
});

test("commented release markers do not hide an ordinary PR", async () => {
  const { run } = fixture({ prs: [{ ...pull(543),
    body: "<!--\nRelease: required\n-->\n" + pull(543).body }] });
  assert.equal((await run()).entries.length, 1);
});

test("latest included stable release on the version line excludes ahead main, drafts and prereleases", async () => {
  const { run, calls } = fixture({ releases: [release("v2.5.0"), release("v1.99.0"),
    release("v2.8.0", { draft: true }), release("v2.7.0", { prerelease: true }),
    release("v3.0.0"), release("v2.6.0"), release("v2.6.1"), release("v2.6.2")],
  requestHook: path => path.includes("/compare/v2.6.2") ? { status: "diverged", base_commit: { sha: later } }
    : path.includes("/compare/v2.6.1") ? { status: "behind", base_commit: { sha: later } } : undefined });
  assert.equal((await run()).baseline.version, "2.6.0");
  assert.deepEqual(calls.filter(path => path.startsWith("/compare/")),
    ["v2.6.2", "v2.6.1", "v2.6.0"].map(tag => `/compare/${tag}...${head}?per_page=100&page=1`));
});

test("a new official release removes notes already included in its baseline", async () => {
  const { run, calls } = fixture({ releases: [release("v2.6.0"), release("v2.6.1")],
    requestHook: path => path.startsWith("/compare/v2.6.1") ? {
      status: "identical", base_commit: { sha: head }, total_commits: 0, commits: [],
    } : undefined });
  const result = await run();
  assert.equal(result.baseline.version, "2.6.1");
  assert.deepEqual(result.entries, []);
  assert.equal(calls.some(path => path.startsWith("/pulls?")), false);
});

test("commit and PR pagination complete before an empty result can be reported", async () => {
  const commits = Array.from({ length: 100 }, (_, n) => n.toString(16).padStart(40, "0"));
  const { run } = fixture({ requestHook: path => {
    if (path.startsWith("/compare/")) return {
      status: "ahead", base_commit: { sha: base }, total_commits: 101,
      commits: (path.endsWith("page=1") ? commits : [merged]).map(sha => ({ sha })),
    };
    if (path.startsWith("/pulls?")) return path.endsWith("page=1")
      ? Array.from({ length: 100 }, (_, n) => pull(n + 1, later)) : [pull(543)];
  } });
  assert.equal((await run()).entries[0].number, 543);
});

test("pagination failure, invalid/missing notes and unknown release fail closed", async () => {
  const broken = fixture({ requestHook: path => {
    if (path.startsWith("/pulls?")) throw new Error("rate limited");
  } });
  await assert.rejects(broken.run(), /rate limited/);
  await assert.rejects(fixture({ releases: [] }).run(), /No included stable release/);
  await assert.rejects(fixture({ prs: [{ ...pull(1), body: "" }] }).run(), /Missing pending/);
  await assert.rejects(fixture({ requestHook: path => path.startsWith("/compare/")
    ? { status: "ahead", base_commit: { sha: base }, total_commits: 2, commits: [{ sha: merged }] } : undefined }).run(), /Incomplete commit/);
  await assert.rejects(fixture({ requestHook: path => path.startsWith("/releases?") ? {} : undefined }).run(), /Invalid GitHub page/);
});

test("failure becomes unavailable metadata without aborting the build or leaking errors", async t => {
  const root = mkdtempSync(join(tmpdir(), "unreleased-"));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const git = args => execFileSync("git", args, { cwd: root, stdio: "pipe" });
  git(["init"]);
  writeFileSync(join(root, "VERSION"), "2.6.0");
  git(["add", "VERSION"]);
  git(["-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "fixture"]);
  const result = await localUnreleased(root,
    async () => { throw new Error("offline"); });
  assert.equal(result.status, "unavailable");
  assert.match(result.head, /^[a-f0-9]{40}$/);
  assert.deepEqual(result.entries, []);
  assert.equal("error" in result, false);
});

test("pending section parsing handles CRLF, comments, None and heading boundaries", () => {
  assert.equal(pendingNotes("## Pending release notes\r\n<!-- placeholder -->\r\n- One\r\n### Detail\r\nmore\r\n## Validation\r\nsecret"), "- One\n### Detail\nmore");
  assert.equal(pendingNotes("## Pending release notes\nNone"), null);
  assert.equal(pendingNotes("## Pending release notes\n<!-- other -->\nNone."), null);
  assert.throws(() => pendingNotes("## Pending release notes\n<!-- none -->"), /Missing pending/);
});

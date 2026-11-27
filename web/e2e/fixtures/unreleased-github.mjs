// Build/server-side fixture only; never imported by application code.
import { readFileSync } from "node:fs";
const version = readFileSync(new URL("../../../VERSION", import.meta.url), "utf8").trim();
const originalFetch = globalThis.fetch;
globalThis.fetch = async (url, options) => {
  if (!String(url).startsWith("https://api.github.com/repos/Yuto-24/NavMate/")) return originalFetch(url, options);
  const scenario = process.env.UNRELEASED_SCENARIO;
  if (scenario === "unavailable") return new Response("offline", { status: 503 });
  const path = new URL(url).pathname;
  let data;
  if (path.endsWith("/releases")) data = [{ tag_name: `v${version}`, draft: false, prerelease: false }];
  else if (path.includes("/compare/")) {
    const head = path.split("...")[1];
    data = { status: scenario === "empty" ? "identical" : "ahead", base_commit: { sha: "b".repeat(40) },
      total_commits: scenario === "empty" ? 0 : 1, commits: scenario === "empty" ? [] : [{ sha: head }] };
  } else if (path.endsWith("/pulls")) {
    data = [{ number: 543, title: "ISSUE543_UNRELEASED_SENTINEL", merged_at: "2026-11-27T00:00:00Z",
      merge_commit_sha: process.env.UNRELEASED_HEAD,
      body: "## Pending release notes\n- このビルドに含まれる変更を確認できます。" }];
  } else throw new Error(`Unexpected fixture path: ${path}`);
  return Response.json(data);
};

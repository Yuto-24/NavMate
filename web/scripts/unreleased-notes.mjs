import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";

const repository = "Yuto-24/NavMate";
const api = `https://api.github.com/repos/${repository}`;
const stableTag = /^v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/;
const sha = /^[a-f0-9]{40}$/;

export function pendingNotes(body) {
  const visible = (body ?? "").replace(/<!--[\s\S]*?-->/g, "").replace(/\r\n/g, "\n");
  const section = visible.match(/^## Pending release notes[ \t]*\n([\s\S]*?)(?=^ {0,3}#{1,2}(?:[ \t]|$)|$(?![\s\S]))/m)?.[1].trim();
  if (!section) throw new Error("Missing pending release notes");
  return /^None[.!]?$/i.test(section) ? null : section;
}

// No credentials, browser requests, or search-index lag. One bounded build-time snapshot.
export function githubSnapshot() {
  const signal = AbortSignal.timeout(30_000);
  let requests = 0;
  return async (path) => {
    if (++requests > 100) throw new Error("GitHub request budget exceeded");
    const response = await fetch(`${api}${path}`, {
      headers: { Accept: "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28" },
      signal,
    });
    if (!response.ok) throw new Error(`GitHub returned ${response.status}`);
    return response.json();
  };
}

async function pages(request, path) {
  const rows = [];
  for (let page = 1; page <= 100; page++) {
    const batch = await request(`${path}${path.includes("?") ? "&" : "?"}per_page=100&page=${page}`);
    if (!Array.isArray(batch)) throw new Error("Invalid GitHub page");
    rows.push(...batch);
    if (batch.length < 100) return rows;
  }
  throw new Error("Incomplete GitHub pagination");
}

export async function collectUnreleased({ head, version, request = githubSnapshot() }) {
  if (!sha.test(head) || !/^\d+\.\d+\.\d+$/.test(version)) throw new Error("Invalid build identity");
  const releases = (await pages(request, "/releases"))
    .filter(release => !release.draft && !release.prerelease && stableTag.test(release.tag_name)
      && release.tag_name.slice(1).split(".")[0] === version.split(".")[0])
    .sort((a, b) => {
      const left = a.tag_name.slice(1).split(".").map(Number);
      const right = b.tag_name.slice(1).split(".").map(Number);
      for (let i = 0; i < 3; i++) if (left[i] !== right[i]) return right[i] - left[i];
      return 0;
    });
  let baseline, comparison;
  for (const release of releases) {
    const result = await request(`/compare/${release.tag_name}...${head}?per_page=100&page=1`);
    if (!["ahead", "identical", "behind", "diverged"].includes(result.status)
      || !sha.test(result.base_commit?.sha)) throw new Error("Invalid release comparison");
    if (["ahead", "identical"].includes(result.status)) {
      baseline = { version: release.tag_name.slice(1), commit: result.base_commit.sha };
      comparison = result;
      break;
    }
  }
  if (!baseline) throw new Error("No included stable release on this version line");
  const commits = new Set();
  let page = 1;
  while (true) {
    if (!Array.isArray(comparison.commits) || !Number.isSafeInteger(comparison.total_commits)
      || comparison.total_commits < 0 || comparison.commits.some(commit => !sha.test(commit.sha))) {
      throw new Error("Invalid commit comparison");
    }
    for (const commit of comparison.commits) commits.add(commit.sha);
    if (commits.size === comparison.total_commits) break;
    if (comparison.commits.length < 100 || ++page > 100) throw new Error("Incomplete commit comparison");
    comparison = await request(`/compare/${baseline.commit}...${head}?per_page=100&page=${page}`);
  }
  const entries = [];
  if (commits.size) for (const pr of await pages(request, "/pulls?state=closed&sort=updated&direction=desc")) {
    if (!pr.merged_at || !commits.has(pr.merge_commit_sha)) continue;
    if (!Number.isSafeInteger(pr.number) || pr.number <= 0 || typeof pr.title !== "string") {
      throw new Error("Invalid pull request");
    }
    // Release-preparation PRs have finalized CHANGELOG notes, not pending notes.
    if (/^Release:[ \t]*required[ \t]*$/m.test(pr.body ?? "")) continue;
    const notes = pendingNotes(pr.body);
    if (notes) entries.push({ number: pr.number, title: pr.title, notes });
  }
  entries.sort((a, b) => b.number - a.number);
  return { status: "ready", head, baseline, entries };
}

export async function localUnreleased(root, request) {
  const head = execFileSync("git", ["rev-parse", "HEAD"], { cwd: root, encoding: "utf8" }).trim();
  try {
    return await collectUnreleased({ head, version: readFileSync(`${root}/VERSION`, "utf8").trim(), request });
  } catch (error) {
    console.warn(`Local Docker unreleased notes unavailable: ${error.message}`);
    return { status: "unavailable", head, entries: [] };
  }
}

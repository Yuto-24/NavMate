// Source checks only. Real candidate build, inventory and E2E always run again.
import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

const root = resolve(process.cwd());
const hash = file => createHash("sha256").update(readFileSync(resolve(root, file))).digest("hex");
const command = (program, args) => execFileSync(program, args, { encoding: "utf8" }).trim();
const inputs = () => ({
  sha: command("git", ["rev-parse", "HEAD"]),
  clean: command("git", ["status", "--porcelain", "--untracked-files=normal"]) === "",
  node: process.version, npm: command("npm", ["--version"]),
  platform: process.platform, arch: process.arch,
  lock: hash("web/package-lock.json"), package: hash("web/package.json"),
});
const [mode, file, check = "typecheck"] = process.argv.slice(2);
if (mode === "write" && file) {
  const current = inputs();
  if (!current.clean) throw new Error("Source CI inventory requires an unchanged checkout");
  writeFileSync(file, JSON.stringify({
    ...current, git: command("git", ["--version"]), workflow: hash(".github/workflows/test.yml"),
    producer: hash("web/scripts/source-ci-inventory.mjs"),
    run_id: process.env.GITHUB_RUN_ID, run_attempt: process.env.GITHUB_RUN_ATTEMPT,
  }) + "\n");
} else if (mode === "matches" && file) {
  try {
    const recorded = JSON.parse(readFileSync(file, "utf8"));
    const current = inputs();
    if (check === "test:static-artifact") current.git = command("git", ["--version"]);
    else if (check !== "typecheck") process.exit(1);
    process.exit(Object.entries(current).every(([key, value]) => recorded[key] === value) ? 0 : 1);
  } catch { process.exit(1); }
} else {
  throw new Error("Expected write/matches and an inventory path");
}

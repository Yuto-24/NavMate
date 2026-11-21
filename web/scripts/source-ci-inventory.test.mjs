import { test } from "node:test";
import assert from "node:assert/strict";
import { execFileSync, spawnSync } from "node:child_process";
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const script = fileURLToPath(new URL("./source-ci-inventory.mjs", import.meta.url));
test("inventory checks bind the app SHA, locked inputs and each check's toolchain", () => {
  const root = mkdtempSync(join(tmpdir(), "navmate-source-ci-"));
  try {
    for (const directory of ["web/scripts", ".github/workflows"]) mkdirSync(join(root, directory), { recursive: true });
    for (const path of ["web/package.json", "web/package-lock.json", ".github/workflows/test.yml",
      "web/scripts/source-ci-inventory.mjs"]) writeFileSync(join(root, path), "{}\n");
    writeFileSync(join(root, ".gitignore"), "inventory.json\n");
    const git = args => execFileSync("git", args, { cwd: root, stdio: "pipe" });
    git(["init"]); git(["add", "."]);
    git(["-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "fixture"]);
    const file = join(root, "inventory.json");
    const run = (mode, check = "typecheck") => spawnSync(process.execPath, [script, mode, file, check], {
      cwd: root, env: { ...process.env, GITHUB_RUN_ID: "42", GITHUB_RUN_ATTEMPT: "2" },
    }).status;
    assert.equal(run("write"), 0);
    const value = JSON.parse(readFileSync(file, "utf8"));
    assert.equal(value.run_id, "42");
    assert.equal(run("matches"), 0);
    assert.equal(run("matches", "test:static-artifact"), 0);
    for (const key of ["sha", "node", "npm", "platform", "arch", "lock", "package"]) {
      writeFileSync(file, JSON.stringify({ ...value, [key]: "changed" }));
      assert.equal(run("matches"), 1, key);
      assert.equal(run("matches", "test:static-artifact"), 1, key);
    }
    writeFileSync(file, JSON.stringify({ ...value, git: "changed" }));
    assert.equal(run("matches"), 0);
    assert.equal(run("matches", "test:static-artifact"), 1);
    writeFileSync(file, JSON.stringify(value));
    writeFileSync(join(root, "web/scripts/source-ci-inventory.mjs"), "changed");
    assert.equal(run("matches"), 1);
    assert.equal(run("write"), 1);
    writeFileSync(join(root, "web/scripts/source-ci-inventory.mjs"), "{}\n");
    writeFileSync(join(root, "web/package-lock.json"), "changed");
    assert.equal(run("matches"), 1);
    writeFileSync(file, "null");
    assert.equal(run("matches"), 1);
  } finally { rmSync(root, { recursive: true, force: true }); }
});

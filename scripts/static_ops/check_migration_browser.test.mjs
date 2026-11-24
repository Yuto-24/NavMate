import { execFileSync, spawnSync } from 'node:child_process';
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';
import test from 'node:test';

const checker = fileURLToPath(new URL('./check_migration_browser.mjs', import.meta.url));
for (const side of ['current', 'candidate']) {
  for (const extension of [null, '', '.js', '.mjs', '.mts', '.jsx', '.tsx', '.json']) {
    test(`${side} sibling ${extension ?? '(none)'}`, () => {
      const root = mkdtempSync(join(tmpdir(), 'migration-resolver-'));
      const git = (...args) => execFileSync('git', args, { cwd: root, encoding: 'utf8' }).trim();
      const commit = () => { git('add', '.'); git('commit', '--quiet', '--allow-empty', '-m', 'fixture'); return git('rev-parse', 'HEAD'); };
      try {
        git('init', '--quiet'); git('config', 'user.email', 'test@example.invalid'); git('config', 'user.name', 'Test');
        mkdirSync(join(root, 'web/src'), { recursive: true });
        for (const name of ['localProjectRepository', 'accountProjectRepository', 'firestoreSyncRepository']) {
          writeFileSync(join(root, 'web/src', name + '.ts'), 'import { value } from "./helper"; export { value };');
        }
        writeFileSync(join(root, 'web/src/helper.ts'), 'export const value = 1;');
        const sibling = () => writeFileSync(join(root, 'web/src/helper' + extension), 'export const value = 2;');
        if (side === 'current' && extension !== null) sibling();
        const current = commit();
        if (side === 'current' && extension !== null) rmSync(join(root, 'web/src/helper' + extension));
        if (side === 'candidate' && extension !== null) sibling();
        const candidate = commit();
        const result = spawnSync(process.execPath, [checker, current, candidate], { cwd: root, encoding: 'utf8' });
        if (extension === null) {
          assert.equal(result.status, 0, result.stderr);
          assert.match(JSON.parse(result.stdout)['helper.ts'], /^[0-9a-f]{64}$/);
        } else {
          assert.notEqual(result.status, 0);
          assert.match(result.stderr, /Ambiguous browser dependency resolution/);
        }
      } finally {
        rmSync(root, { recursive: true, force: true });
      }
    });
  }
}

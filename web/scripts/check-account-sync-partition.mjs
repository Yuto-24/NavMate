import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const web = resolve(dirname(fileURLToPath(import.meta.url)), '..');
export const projects = ['chromium', 'ipad-webkit', 'iphone-webkit'];

export function identities(report) {
  assert.deepEqual(report.errors ?? [], [], 'Playwright collection errors');
  const found = [];
  const visit = suite => {
    for (const spec of suite.specs ?? []) {
      for (const test of spec.tests) {
        found.push(JSON.stringify([spec.file, spec.line, spec.column, spec.title, test.projectName]));
      }
    }
    for (const child of suite.suites ?? []) visit(child);
  };
  for (const suite of report.suites) visit(suite);
  assert.ok(found.length, 'empty collection');
  return found.sort();
}

export function verify(full, shards) {
  assert.deepEqual(shards.flat().sort(), full, 'project partition omitted or duplicated tests');
}

function collect(config, project, shard) {
  const args = [resolve(web, 'node_modules/@playwright/test/cli.js'), 'test',
    '--config', `playwright.${config}.config.ts`, '--list', '--reporter=json'];
  if (project) args.push('--project', project);
  if (shard) args.push('--fully-parallel', '--workers=1', `--shard=${shard}/2`);
  return identities(JSON.parse(execFileSync(process.execPath, args,
    { cwd: web, encoding: 'utf8', maxBuffer: 16 * 1024 * 1024 })));
}

export function verifyMatrix(block, expected) {
  const matrix = block?.match(/      matrix:\n([\s\S]*?)\n    steps:/)?.[1];
  assert.equal(matrix?.split('\n').map(line => line.trim()).join('\n'), expected.join('\n'),
    'workflow matrix must run every collected shard exactly once');
}

export function check() {
  const workflow = readFileSync(resolve(web, '../.github/workflows/test.yml'), 'utf8');
  const block = workflow.split('  account-sync-tests:\n')[1]?.split('\n  account-sync:\n')[0];
  verifyMatrix(block, [
    'suite: [chromium, ipad-webkit, iphone-webkit]', 'shard: [1, 2]', 'include:',
    '- {suite: contracts, shard: 1}', '- {suite: dev-shared, shard: 1}',
  ]);
  const full = collect('sync');
  verify(full, projects.flatMap(project => [1, 2].map(shard => collect('sync', project, shard))));
  // Moved helper/dialog cases retain the same three browser/device profiles.
  const components = collect('sync-component');
  verify(components, projects.map(project => collect('sync-component', project)));
  const notifications = collect('notification');
  const localBlock = workflow.split('  local-browser-tests:\n')[1]?.split('\n  local-browser:\n')[0];
  verifyMatrix(localBlock, [
    'suite: [local, acceptance, focused-ux, clipboard, auth]',
    `exclude: \${{ fromJSON(needs.release-sources.result == 'success' && needs.release-sources.outputs.skip_local_auth == 'true' && '[{"suite":"auth"}]' || '[]') }}`,
    'shard: [1]', 'include:',
    '- {suite: local, shard: 2}', '- {suite: local, shard: 3}', '- {suite: local, shard: 4}',
  ]);
  const local = shard => identities(JSON.parse(execFileSync('npm', [
    '--silent', 'run', 'test:local', '--', '--list', '--reporter=json',
    ...(shard ? [`--shard=${shard}/4`] : []),
  ], { cwd: web, encoding: 'utf8', maxBuffer: 16 * 1024 * 1024 })));
  const localFull = local();
  verify(localFull, [1, 2, 3, 4].map(local));
  const contracts = Object.fromEntries(['firestore', 'storage-upgrade', 'migration']
    .map(config => [config, collect(config).length]));
  console.log(JSON.stringify({ local: localFull.length, sync: full.length, syncComponents: components.length, notifications: notifications.length, projects, contracts }));
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) check();

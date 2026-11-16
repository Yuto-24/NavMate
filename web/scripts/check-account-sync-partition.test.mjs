import assert from 'node:assert/strict';
import test from 'node:test';
import { identities, verify, verifyMatrix } from './check-account-sync-partition.mjs';

test('partition requires every original test exactly once', () => {
  verify(['a', 'b'], [['b'], ['a']]);
  assert.throws(() => verify(['a', 'b'], [['a']]));
  assert.throws(() => verify(['a', 'b'], [['a'], ['a']]));
  assert.throws(() => verify(['a', 'b'], [['a', 'b'], ['c']]));
});
test('collection includes nested suites and distinct projects and rejects errors', () => {
  const spec = { file: 'sync.spec.ts', line: 1, column: 1, title: 'same title',
    tests: [{ projectName: 'chromium' }, { projectName: 'ipad-webkit' }] };
  const report = { suites: [{ suites: [{ specs: [spec] }] }], errors: [] };
  assert.equal(identities(report).length, 2);
  assert.notEqual(...identities(report));
  assert.throws(() => identities({ suites: [], errors: [] }));
  assert.throws(() => identities({ suites: [], errors: [{ message: 'failed' }] }));
});

test('matrix cannot exclude a collected shard or add duplicate executions', () => {
  const expected = ['suite: [chromium]', 'shard: [1, 2]'];
  const block = lines => `      matrix:\n${lines.map(line => `        ${line}`).join('\n')}\n    steps:`;
  verifyMatrix(block(expected), expected);
  assert.throws(() => verifyMatrix(block(['suite: [chromium]', 'shard: [1]']), expected));
  assert.throws(() => verifyMatrix(block([...expected, 'exclude:', '- {shard: 2}']), expected));
  assert.throws(() => verifyMatrix(block([...expected, 'include:', '- {shard: 3}']), expected));
  assert.throws(() => verifyMatrix('', expected));
});

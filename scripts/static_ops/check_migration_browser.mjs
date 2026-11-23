// Read pinned TypeScript as data. Do not import or execute candidate modules.
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { posix } from 'node:path';
import { transformSync, parseSync, Visitor } from '../../web/node_modules/rolldown/dist/utils-index.mjs';

const [current, candidate] = process.argv.slice(2);
if (![current, candidate].every(sha => /^[0-9a-f]{40}$/.test(sha ?? ''))) {
  throw Error('Full application identities required');
}
const roots = new Set(['localProjectRepository.ts', 'accountProjectRepository.ts',
  'firestoreSyncRepository.ts']);
const source = (sha, name) => execFileSync('git', ['show', `${sha}:web/src/${name}`],
  { encoding: 'utf8', maxBuffer: 4 * 1024 * 1024 });
const emit = text => {
  const result = transformSync('source.ts', text, { lang: 'ts', target: 'es2022' });
  if (result.errors.length) throw Error('Browser dependency did not compile');
  return result.code;
};
const seen = new Set(), results = {};
function inspect(name) {
  if (seen.has(name)) return;
  seen.add(name);
  if (seen.size > 100 || !/^[A-Za-z0-9_./-]+\.ts$/.test(name) || name.includes('..')) {
    throw Error('Unsupported browser dependency graph');
  }
  const before = emit(source(current, name));
  if (!roots.has(name)) {
    if (before !== emit(source(candidate, name))) {
      throw Error('Old browser runtime dependency changed');
    }
    results[name] = createHash('sha256').update(before).digest('hex');
  }
  const parsed = parseSync('module.js', before);
  if (parsed.errors.length) throw Error('Browser dependency did not parse');
  function dependency(node) {
    if (!node.source) return;
    const specifier = node.source.value;
    if (typeof specifier !== 'string') throw Error('Nonliteral module dependency');
    if (specifier.startsWith('./')) {
      inspect(posix.join(posix.dirname(name), specifier) + '.ts');
    } else if (!['firebase/app', 'firebase/auth', 'firebase/firestore'].includes(specifier)) {
      throw Error('Unsupported runtime dependency');
    }
  }
  new Visitor({
    ImportDeclaration: dependency, ExportNamedDeclaration: dependency,
    ExportAllDeclaration: dependency,
    ImportExpression() { throw Error('Dynamic dependencies require individual review'); },
    CallExpression(node) {
      if (node.callee.type === 'Identifier' && node.callee.name === 'require') {
        throw Error('Dynamic dependencies require individual review');
      }
    },
  }).visit(parsed.program);
}
for (const name of roots) inspect(name);
process.stdout.write(JSON.stringify(results));

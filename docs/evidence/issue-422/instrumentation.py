"""Apply temporary timing marks to a disposable benchmark checkout, not a release."""
import sys
from pathlib import Path

root = Path(sys.argv[1])
worker = root / "web/src/local.worker.ts"
source = worker.read_text()
assert 'performance.mark("startup:' not in source
for before, after in [
    ('async function initialize() {',
     'async function initialize() {\n  performance.mark("startup:pyodide:start");'),
    ('  await pyodide.loadPackage(',
     '  performance.mark("startup:pyodide:end");\n'
     '  performance.mark("startup:packages:start");\n  await pyodide.loadPackage('),
    ('  const assetUrl =',
     '  performance.mark("startup:packages:end");\n'
     '  performance.mark("startup:assets:start");\n  const assetUrl ='),
    ('  pyodide.runPython(`\nfrom pathlib',
     '  performance.mark("startup:assets:end");\n'
     '  performance.mark("startup:application:start");\n  pyodide.runPython(`\nfrom pathlib'),
    ('  return pyodide;',
     '  performance.mark("startup:application:end");\n  return pyodide;'),
]:
    assert source.count(before) == 1, before
    source = source.replace(before, after, 1)
worker.write_text(source)
main = root / "web/src/main.tsx"
source = main.read_text()
start = 'startApplication(browserPlatform, ({ application, platform }) => {'
assert source.count(start) == 1
main.write_text(source.replace(start, 'performance.mark("startup:authentication:start");\n'
    + start + '\n  performance.mark("startup:authentication:end");', 1))

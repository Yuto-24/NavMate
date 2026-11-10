import { defineConfig } from "vite";
import { resolve } from "node:path";
import { execFileSync } from "node:child_process";
export default defineConfig({
  define: { __LOCAL_MANIFEST_SHA256__: '""', __PYODIDE_VERSION__: '"0.27.7"' },
  plugins: [{ name: "historical-repository-dependencies", enforce: "pre", resolveId(source, importer) {
    if ((importer?.includes("/e2e/fixtures/v1.20.1/") || importer?.includes("/e2e/fixtures/v2.2.2/")) && source.startsWith("./") && source !== "./localProjectRepository") {
      return resolve("src", source + ".ts");
    }
  } }, { name: "schema5-domain-validation", configureServer(server) {
    // Test-only bridge to the candidate's real Python validation/conflict cleanup.
    server.middlewares.use("/__schema5_record", async (req, res) => {
      try {
        const chunks = [];
        for await (const chunk of req) chunks.push(chunk);
        const result = execFileSync(process.env.AUTONAVLOG_REFERENCE_PYTHON ?? "python3", ["-c", `
import json,sys
from pathlib import Path
from autonavlog.local import LocalApplication
request=json.load(sys.stdin)
app=LocalApplication(Path('data'))
try: print(app.dispatch(request['operation'],request['payload']))
finally: app.close()
`], { cwd: resolve(".."), input: Buffer.concat(chunks), maxBuffer: 4 * 1024 * 1024,
          env: { ...process.env, PYTHONPATH: resolve("../src"), PYTHONDONTWRITEBYTECODE: "1" },
          stdio: ["pipe", "pipe", "pipe"] });
        res.setHeader("Content-Type", "application/json"); res.end(result);
      } catch { res.statusCode = 422; res.end("domain validation failed"); }
    });
  } }],
  server: { host: "127.0.0.1", port: 5189, strictPort: true },
});

import { resolve } from "node:path";
import { checkArtifact } from "./static-artifact.mjs";
const args = process.argv.slice(2);
const expectedCommits = args.filter(arg => arg.startsWith("--expected-commit="));
if (expectedCommits.length > 1 || args.some(arg => arg.startsWith("--")
  && !["--allow-dirty", "--allow-expired-weather", "--local-runtime"].includes(arg)
  && !/^--expected-commit=[a-f0-9]{40}$/.test(arg))) {
  throw new Error("Unknown check:static option");
}
console.log(JSON.stringify(checkArtifact(resolve(args.find(arg => !arg.startsWith("--")) ?? "dist-static"),
  { freshWeather: !args.includes("--allow-expired-weather"), allowDirty: args.includes("--allow-dirty"),
    localRuntime: args.includes("--local-runtime"), expectedCommit: expectedCommits[0]?.split("=")[1] }), null, 2));

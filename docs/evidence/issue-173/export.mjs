// Node 22: use the product serializer directly, with native type stripping.
// Run from the repository root; output directory contains generate.py results.
import { readFileSync, writeFileSync, readdirSync } from "node:fs";
import { resolve } from "node:path";
import { exportVerticalProfileKml } from "../../../web/src/verticalProfileKml.ts";
const directory = process.argv[2];
for (const file of readdirSync(directory).filter(name => name.endsWith(".profile.json"))) {
  const profile = JSON.parse(readFileSync(resolve(directory, file), "utf8"));
  writeFileSync(resolve(directory, file.replace(".profile.json", ".kml")), exportVerticalProfileKml(profile, false).content);
}

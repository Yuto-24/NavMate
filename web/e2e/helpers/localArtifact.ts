import { test as base, type BrowserContext } from "@playwright/test";

// The local updater passes the same flag to the candidate build and its browser checks.
// Cloud synchronization is covered separately against emulators; artifact acceptance
// must never create Auth users or write Projects in the real development project.
const shared = process.env.VITE_DEV_SHARED_PROJECTS === "1";
const suffix = shared ? ".dev_shared_navmate-6b281" : "";
export const artifactDatabase = "autonavlog.projects" + suffix;
export const artifactSessionKey = "autonavlog.working-session.v1" + suffix;
export async function blockDevCloud(context: BrowserContext) {
  if (shared) await context.route(/^https:\/\/[^/]*\.(googleapis\.com|firebaseio\.com|firebaseapp\.com)\//,
    route => route.abort("blockedbyclient"));
}
export const test = base.extend({
  context: async ({ context }, use) => {
    await blockDevCloud(context);
    await use(context);
  },
});

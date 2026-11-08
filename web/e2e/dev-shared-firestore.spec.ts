import { test, expect } from "@playwright/test";
import { initializeApp, deleteApp } from "firebase/app";
import { collection, connectFirestoreEmulator, doc, getDoc, getFirestore, setDoc, terminate } from "firebase/firestore";
import { FirestoreSyncRepository } from "../src/firestoreSyncRepository";
import type { SyncProject } from "../src/accountSync";

function client(provider = "anonymous") {
  const app = initializeApp({ projectId: "navmate-6b281", apiKey: "emulator-only" }, crypto.randomUUID());
  const db = getFirestore(app);
  connectFirestoreEmulator(db, "127.0.0.1", 8089, { mockUserToken: {
    sub: crypto.randomUUID(), firebase: { sign_in_provider: provider, identities: {} },
  } });
  const projects = collection(db, "devWorkspaces", "shared", "projects");
  return { db, projects, repository: new FirestoreSyncRepository(db, "", () => {}, undefined, projects),
    close: async () => { await terminate(db); await deleteApp(app); } };
}

test("different anonymous visitors share the dev workspace with CAS and durable deletion", async () => {
  const a = client(), b = client(), google = client("google.com");
  const id = crypto.randomUUID();
  const value = { id, revision: 1, version: crypto.randomUUID(), latestDeviceId: null,
    deletion: "ACTIVE", undoUntil: null, record: { id, nested: [[1, 2]] } } as unknown as SyncProject;
  try {
    expect(await a.repository.commit([{ expectedVersion: null, value }])).toEqual({ committed: true });
    expect((await b.repository.list()).find(row => row.id === id)?.record).toEqual(value.record);
    const changed = { ...value, version: crypto.randomUUID(), revision: 2 };
    expect(await b.repository.commit([{ expectedVersion: value.version, value: changed }])).toEqual({ committed: true });
    expect((await a.repository.commit([{ expectedVersion: value.version, value: { ...value, version: crypto.randomUUID() } }])).committed).toBe(false);
    const ref = doc(a.projects, id), raw = (await getDoc(ref)).data()!;
    await expect(setDoc(ref, { ...raw, baseVersion: null, version: "stale" })).rejects.toMatchObject({ code: "permission-denied" });
    await expect(getDoc(doc(a.db, "googleAccounts", "another-user", "projects", id))).rejects.toMatchObject({ code: "permission-denied" });
    await expect(google.repository.list()).rejects.toMatchObject({ code: "permission-denied" });
    const deleted = { ...changed, revision: 3, version: crypto.randomUUID(), deletion: "DELETED" as const };
    expect(await a.repository.commit([{ expectedVersion: changed.version, value: deleted }])).toEqual({ committed: true });
    await expect(setDoc(ref, { ...raw, baseVersion: deleted.version, revision: 4, version: "revive" })).rejects.toMatchObject({ code: "permission-denied" });
  } finally { await Promise.all([a.close(), b.close(), google.close()]); }
});

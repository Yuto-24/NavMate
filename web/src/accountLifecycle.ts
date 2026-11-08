import { getApp } from "firebase/app";
import { getAuth, type User } from "firebase/auth";
import { collection, doc, getDocFromServer, getDocsFromServer, getFirestore, limit, query, runTransaction, writeBatch } from "firebase/firestore";
import { googleAccount } from "./firebaseAuthProvider";
import { SESSION_KEY } from "./applicationSession";
import { LOCAL_DATABASE, LOCAL_DATABASE_VERSION } from "./localProjectRepository";
import { devSharedMode, localAccountScope } from "./executionMode";

type AccountRecord = { schema: 1; accountId: string; state: "ACTIVE" | "DELETING" | "DELETED" };
const subjectOf = (user: User) => {
  const identities = user.providerData.filter(identity => identity.providerId === "google.com");
  if (identities.length !== 1 || user.providerData.length !== 1 || !identities[0]?.uid) throw new Error("Google アカウントで再認証してください。");
  return identities[0].uid;
};
const recordRef = (user: User) => doc(getFirestore(getApp()), "googleAccounts", subjectOf(user));
const localKey = (user: User) => `autonavlog.account.current.${devSharedMode ? "dev_navmate-6b281." : ""}${subjectOf(user)}`;
const retired = (value: string) => `retired:${value}`;
const cachedId = (value: string | null) => value?.startsWith("retired:") ? value.slice(8) : value;
const onlineRequired = () => new Error("アカウント削除にはオンライン接続と再認証が必要です。");

export async function currentAccount(user: User, register = false, closeOldContext: () => void = () => {}, assertCurrent: () => void = () => {}): Promise<{ accountId: string; deleting: boolean }> {
  const legacyId = (await googleAccount(user)).account_id;
  assertCurrent();
  const key = localKey(user);
  let serverConfirmedInactive = false;
  let deletedGeneration = false;
  if (!navigator.onLine) {
    const cached = localStorage.getItem(key);
    if (cached && !cached.startsWith("retired:")) return { accountId: cached, deleting: false };
    throw new Error("オンライン接続と再認証が必要です。");
  }
  try {
    const ref = recordRef(user);
    const snapshot = await getDocFromServer(ref);
    assertCurrent();
    let value = snapshot.data() as AccountRecord | undefined;
    if (!value) {
      value = { schema: 1, accountId: legacyId, state: "ACTIVE" };
      await runTransaction(ref.firestore, async transaction => {
        const existing = await transaction.get(ref);
        assertCurrent();
        if (!existing.exists()) transaction.set(ref, value!);
        else value = existing.data() as AccountRecord;
      });
    }
    assertCurrent();
    if (value.schema !== 1 || typeof value.accountId !== "string") throw new Error("アカウント情報を確認できません。");
    serverConfirmedInactive = value.state !== "ACTIVE";
    const cached = localStorage.getItem(key);
    const previous = cachedId(cached);
    deletedGeneration = value.state === "DELETED" || (!!previous &&
      (previous !== value.accountId || (value.state === "ACTIVE" && cached?.startsWith("retired:") === true)));
    if (value.state !== "ACTIVE" || (previous && previous !== value.accountId)) closeOldContext();
    if (value.state !== "ACTIVE" || (previous && previous !== value.accountId))
      localStorage.setItem(key, retired(previous ?? value.accountId));
    if (!register && previous && previous !== value.accountId) {
      await removeLocalAccount(previous);
      assertCurrent();
      throw new Error("ACCOUNT_DELETED");
    }
    if (value.state === "DELETING") {
      try {
        await removeLocalAccount(value.accountId);
        if (previous && previous !== value.accountId) await removeLocalAccount(previous);
      } catch (error) {
        throw new Error("ACCOUNT_DELETION_PENDING", { cause: error });
      }
      assertCurrent();
      // Explicit login may select a deleting successor for cleanup retry, while
      // its retired marker must still forbid reopening Local work offline.
      if (register) localStorage.setItem(key, retired(value.accountId));
      return { accountId: value.accountId, deleting: true };
    }
    if (value.state === "DELETED") {
      await removeLocalAccount(value.accountId);
      if (previous && previous !== value.accountId) await removeLocalAccount(previous);
      assertCurrent();
      if (!register) {
        throw new Error("ACCOUNT_DELETED");
      }
      const next = { schema: 1, accountId: `account_v2_${crypto.randomUUID()}`, state: "ACTIVE" } as const;
      value = await runTransaction(ref.firestore, async transaction => {
        const existing = (await transaction.get(ref)).data() as AccountRecord;
        assertCurrent();
        if (existing.state !== "DELETED") return existing;
        transaction.set(ref, next);
        return next;
      });
    }
    if (previous && previous !== value.accountId) await removeLocalAccount(previous);
    if (value.accountId !== legacyId) await removeLocalAccount(legacyId);
    assertCurrent();
    // Keep the retired marker until deliberate login, even when another device
    // has already registered a successor or Firebase logout persistence failed.
    if (!register && deletedGeneration) throw new Error("ACCOUNT_DELETED");
    localStorage.setItem(key, value.accountId);
    return { accountId: value.accountId, deleting: value.state === "DELETING" };
  } catch (error) {
    assertCurrent();
    // A failed Local purge must not retain authentication for a deleted owner.
    // Keep its retired marker so explicit login can retry cleanup before entry.
    if (!register && deletedGeneration && (error as Error)?.message !== "ACCOUNT_DELETED")
      throw new Error("ACCOUNT_DELETED", { cause: error });
    // Cached identity permits existing Local work during an outage. A missing
    // cache on a fresh device must never guess which generation owns its data.
    if (!serverConfirmedInactive && (!navigator.onLine || ["unavailable", "deadline-exceeded"].includes((error as { code?: string })?.code ?? ""))) {
      const cached = localStorage.getItem(key);
      if (cached && !cached.startsWith("retired:")) return { accountId: cached, deleting: false };
    }
    throw error;
  }
}

export async function removeLocalAccount(accountId: string): Promise<void> {
  const scope = localAccountScope(accountId);
  await new Promise<void>((resolve, reject) => {
    const request = indexedDB.deleteDatabase(`${LOCAL_DATABASE}.${scope}`);
    const blocked = () => new Error("端末内のデータを削除できませんでした。別のタブを閉じて、削除を再試行してください。");
    // Some browsers leave a blocked delete pending without delivering onblocked.
    // Keep the server in DELETING and make the operation retryable.
    const timeout = setTimeout(() => reject(blocked()), 10_000);
    request.onsuccess = () => { clearTimeout(timeout); resolve(); };
    request.onerror = () => { clearTimeout(timeout); reject(request.error); };
    request.onblocked = () => { clearTimeout(timeout); reject(blocked()); };
  });
  sessionStorage.removeItem(`${SESSION_KEY}.${scope}`);
  // MAP preferences added on main are scoped to the account too.
  const viewportPrefix = `autonavlog.map-viewport.v1.${scope}.`;
  if (typeof localStorage !== "undefined") {
    for (let index = localStorage.length - 1; index >= 0; index--) {
      const key = localStorage.key(index);
      if (key?.startsWith(viewportPrefix)) localStorage.removeItem(key);
    }
  }
  // Dev personal accounts never import anonymous originals. Older production
  // copies and the shared workspace must survive a development-account deletion.
  if (devSharedMode) return;
  // #185 keeps claimed anonymous originals for interrupted import recovery.
  // Once their owner is deleted, they must not remain as hidden local copies.
  await new Promise<void>((resolve, reject) => {
    const request = indexedDB.open(LOCAL_DATABASE, LOCAL_DATABASE_VERSION);
    let blocked = false;
    request.onblocked = () => {
      blocked = true;
      reject(new Error("端末内のデータを削除できませんでした。別のタブを閉じて、削除を再試行してください。"));
    };
    request.onupgradeneeded = () => {
      if (!request.result.objectStoreNames.contains("projects")) request.result.createObjectStore("projects", { keyPath: "id" });
    };
    request.onerror = () => reject(request.error);
    request.onsuccess = () => {
      const db = request.result;
      if (blocked) { db.close(); return; }
      db.onversionchange = () => db.close();
      const tx = db.transaction("projects", "readwrite");
      const cursor = tx.objectStore("projects").openCursor();
      cursor.onsuccess = () => {
        const row = cursor.result;
        if (!row) return;
        if (row.value?.claimedAccount === accountId) row.delete();
        row.continue();
      };
      tx.oncomplete = () => { db.close(); resolve(); };
      tx.onabort = () => { db.close(); reject(tx.error); };
    };
  });
}

export async function deleteCurrentAccount(user: User, expectedId: string, onDeleting: () => void): Promise<void> {
  if (!navigator.onLine) throw onlineRequired();
  try { await user.getIdToken(true); } catch { throw onlineRequired(); }
  if (getAuth(getApp()).currentUser !== user) throw onlineRequired();
  const ref = recordRef(user);
  const snapshot = await getDocFromServer(ref).catch(() => { throw onlineRequired(); });
  const value = snapshot.data() as AccountRecord | undefined;
  if (!value || value.accountId !== expectedId || value.state === "DELETED") throw new Error("現在のアカウントを確認できません。再ログインしてください。");
  if (value.state === "ACTIVE") await runTransaction(ref.firestore, async transaction => {
    const current = (await transaction.get(ref)).data() as AccountRecord;
    if (current.accountId !== expectedId || current.state !== "ACTIVE") throw new Error("アカウントの状態が変わりました。再試行してください。");
    transaction.update(ref, { state: "DELETING" });
  });
  // The server gate is now durable. An interrupted deletion must not reopen
  // this generation from the deleting device's offline cache.
  localStorage.setItem(localKey(user), retired(expectedId));
  onDeleting();
  const db = getFirestore(getApp());
  const subject = subjectOf(user);
  const projects = expectedId.startsWith("account_v2_")
    ? collection(db, "googleAccounts", subject, "generations", expectedId, "projects")
    : collection(db, "googleAccounts", subject, "projects");
  // The durable DELETING gate denies all reads/writes from old clients. Repeat
  // physical cleanup from the server on retry after any partial batch failure.
  while (true) {
    const rows = await getDocsFromServer(query(projects, limit(10)));
    if (rows.empty) break;
    const batch = writeBatch(db);
    for (const row of rows.docs) batch.delete(row.ref);
    await batch.commit();
  }
  await removeLocalAccount(expectedId);
  await runTransaction(ref.firestore, async transaction => {
    const current = (await transaction.get(ref)).data() as AccountRecord;
    if (current.accountId !== expectedId || current.state !== "DELETING") throw new Error("アカウントの状態が変わりました。再試行してください。");
    transaction.update(ref, { state: "DELETED" });
  });
  // A failed Firebase sign-out must not reopen a successor after reload.
  localStorage.setItem(localKey(user), retired(expectedId));
}

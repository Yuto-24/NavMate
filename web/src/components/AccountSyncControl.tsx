import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { createPortal } from "react-dom";
import type { AccountSyncControl as Control, ConflictChoice, SyncStatus } from "../accountSync";

const empty: SyncStatus = { conflicts: [], imports: [], undo: [], generation: 0 };
const noop = () => () => {};
export function AccountSyncControl({ sync, onChange, onResolved, onBeforeResolve, onErrorChange, onErrorsChange, notificationsManaged = false }: {
  notificationsManaged?: boolean;
  onErrorsChange?: (messages: string[]) => void;
  onErrorChange?: (message: string) => void;
  onBeforeResolve?: () => boolean;
  sync?: Control; onChange(): void; onResolved(id: string): Promise<void>;
}) {
  const state = useSyncExternalStore(sync?.subscribe ?? noop, sync?.getState ?? (() => empty));
  const dialog = useRef<HTMLDialogElement>(null);
  const changed = useRef(onChange); changed.current = onChange;
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [operationErrors, setOperationErrors] = useState<Record<string,string>>({});
  useEffect(() => { onErrorsChange?.(Object.values(operationErrors)); }, [operationErrors, onErrorsChange]);
  const [name, setName] = useState("");
  useEffect(() => { onErrorChange?.(error); }, [error, onErrorChange]);
  const conflict = state.conflicts[0], imported = state.imports[0];
  const blocked = !!(conflict || imported);
  useEffect(() => { changed.current(); }, [state.generation]);
  useEffect(() => {
    if (blocked && !dialog.current?.open) dialog.current?.showModal();
    if (!blocked) dialog.current?.close();
    if (blocked) setError("");
    setName("");
  }, [blocked, conflict?.id, imported?.id]);
  const act = async (operation: () => Promise<void | false>, key: string) => {
    setPending(true); setError("");
    try {
      if (await operation() === false) return;
      setOperationErrors(current => { const next={...current}; delete next[key]; return next; });
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : "操作を完了できませんでした。";
      setError(message);
      setOperationErrors(current => ({...current, [key]:message}));
    }
    finally { setPending(false); }
  };
  const resolve = (choice: ConflictChoice) => conflict && sync && void act(async () => {
    if (onBeforeResolve && !onBeforeResolve()) return false;
    const id = await sync.resolve(conflict.id, choice);
    await onResolved(id);
  }, `resolve:${conflict.id}`);
  return <>
    {!notificationsManaged && state.notice && <div className="message-bar message-error" role="alert">{state.notice}</div>}
    {!notificationsManaged && !blocked && error && <div className="message-bar message-error" role="alert">{error}</div>}
    {state.undo.length > 0 && <div className="sync-undo" role="status">
      {state.undo.map(item => <div key={item.id}><span>「{item.name}」を削除しました。</span>
        <button type="button" disabled={pending} onClick={() => sync && void act(() => sync.undo(item.id), `undo:${item.id}`)}>元に戻す</button></div>)}
    </div>}
    {createPortal(<dialog ref={dialog} className="modal-panel account-sync-dialog" aria-labelledby="sync-title"
      onCancel={event => event.preventDefault()}>
      {conflict ? <>
        <h2 id="sync-title">他の端末の変更と競合しています</h2>
        <p>「{conflict.name}」で再開するデータを選んでください。この端末での編集内容は保存されています。</p>
        <p>「両方残す」は同期先のプロジェクトを維持し、この端末の内容を別プロジェクトとして保存します。</p>
        <div className="modal-actions">
          <button type="button" disabled={pending} onClick={() => resolve("local")}>この端末の内容を採用</button>
          <button type="button" disabled={pending} onClick={() => resolve("remote")}>同期先の内容を採用</button>
          <button type="button" disabled={pending} onClick={() => resolve("both")}>両方残す</button>
        </div>
      </> : imported ? <>
        <h2 id="sync-title">端末内の作業に名前を付けて保存しますか？</h2>
        <p>アカウントの自動保存を引き継ぎます。未ログイン時の自動保存は、名前を付けて保存しない場合は破棄されます。</p>
        <label>プロジェクト名<input maxLength={60} value={name} onChange={event => setName(event.target.value)} autoFocus /></label>
        <div className="modal-actions">
          <button type="button" disabled={pending || !name.trim()} onClick={() => sync && void act(async () => { if (onBeforeResolve && !onBeforeResolve()) return false; await sync.importLatest(imported.id, name); await onResolved(imported.id); }, `import:${imported.id}`)}>名前を付けて保存</button>
          <button type="button" disabled={pending} onClick={() => sync && void act(async () => { if (onBeforeResolve && !onBeforeResolve()) return false; await sync.importLatest(imported.id, null); await onResolved(imported.id); }, `import:${imported.id}`)}>破棄</button>
        </div>
      </> : null}
      {error && <p role="alert">{error}</p>}
    </dialog>, document.body)}
  </>;
}

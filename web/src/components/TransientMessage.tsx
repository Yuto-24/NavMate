import { useEffect, useState } from "react";
import { AlertCircle, CheckCircle2, X } from "lucide-react";

// Expire presentation only: callers retain unresolved state in its owning surface.
export function TransientMessage({ message, revision, kind = "error", className = "" }: {
  message: string | null | undefined; revision?: unknown;
  kind?: "success" | "warning" | "error"; className?: string;
}) {
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    if (!message) { setVisible(false); return; }
    setVisible(true);
    const timeout = window.setTimeout(() => setVisible(false), 5_000);
    return () => window.clearTimeout(timeout);
  }, [message, revision]);
  if (!message || !visible) return null;
  return <div className={`message-bar app-notification message-${kind} ${className}`} role={kind === "error" ? "alert" : "status"}>
    {kind === "success" ? <CheckCircle2 aria-hidden="true" size={18} /> : <AlertCircle aria-hidden="true" size={18} />}
    <span>{message}</span>
    <button type="button" className="icon-button" aria-label="メッセージを閉じる" onClick={() => setVisible(false)}><X aria-hidden="true" size={17} /></button>
  </div>;
}

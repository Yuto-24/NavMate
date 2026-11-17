import { useCallback, useState, type SetStateAction } from "react";

// Every explicit notification, including the same text twice, has a new lifetime.
export function useNotificationState() {
  const [state, update] = useState<{text:string|null;revision:number}>({text:null,revision:0});
  const set = useCallback((value:SetStateAction<string|null>) => update(current => {
    const text = typeof value === "function" ? value(current.text) : value;
    // Conditional fault resolution must not restart an unrelated notification.
    if (typeof value === "function" && text === current.text) return current;
    return {text, revision:current.revision+1};
  }), []);
  return [state.text, set, state.revision] as const;
}

// Build-time developer setting; no user-facing runtime selector or HTTP fallback.
export const localMode = import.meta.env?.VITE_CALCULATION_MODE === "local";

// Only the opt-in local Docker server injects this marker; ordinary artifacts do not.
export const devSharedMode = localMode && typeof document !== "undefined"
  && document.querySelector('meta[name="navmate-dev-shared-projects"]')?.getAttribute("content") === "1";

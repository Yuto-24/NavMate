// Build-time developer settings; ordinary production builds never enable shared development.
export const localMode = import.meta.env?.VITE_CALCULATION_MODE === "local";
export const devSharedMode = localMode && import.meta.env?.VITE_DEV_SHARED_PROJECTS === "1";

// Dev account tests must not open or delete older production-account copies on
// this origin. Shared storage keeps its existing namespace across this change.
export const localAccountScope = (id: string) => devSharedMode ? `dev_navmate-6b281.${id}` : id;

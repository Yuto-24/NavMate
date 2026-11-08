// Build-time developer settings; ordinary production builds never enable shared development.
export const localMode = import.meta.env?.VITE_CALCULATION_MODE === "local";
export const devSharedMode = localMode && import.meta.env?.VITE_DEV_SHARED_PROJECTS === "1";

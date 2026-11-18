export type StartupStage = "authentication" | "runtime" | "download" | "packages" | "application" | "projects" | "ready";
export interface StartupProgress { percent: number; stage: StartupStage }
export type StartupProgressListener = (progress: StartupProgress) => void;

// Stage weights are an overall estimate, not elapsed time. Download fractions
// within a stage come from bytes actually read; CPU work advances on completion.
export function advanceStartup(current: StartupProgress, next: StartupProgress): StartupProgress {
  if (!Number.isFinite(next.percent) || next.percent < current.percent) return current;
  const percent = Math.min(100, Math.max(0, next.percent));
  return current.percent === percent && current.stage === next.stage ? current : { ...next, percent };
}

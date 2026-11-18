export const startupStages = ["authentication", "runtime", "dependencies", "assets", "application", "projects"] as const;
export type StartupStage = typeof startupStages[number];
export interface StartupProgress { stage: StartupStage; percent: number }
export interface StartupProgressSource {
  getSnapshot(): StartupProgress;
  subscribe(listener: () => void): () => void;
  complete(): void;
}

export const authenticationProgress: StartupProgress = { stage: "authentication", percent: 0 };

// One instance per Application/account lifetime. Percentages are milestones,
// not elapsed-time estimates; late events cannot move the bar or stage backwards.
export class StartupProgressStore implements StartupProgressSource {
  private current: StartupProgress = { stage: "runtime", percent: 5 };
  private listeners = new Set<() => void>();
  getSnapshot = () => this.current;
  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  };
  update = (progress: StartupProgress) => {
    if (this.current.percent === 100 || !Number.isFinite(progress.percent) || progress.percent < this.current.percent || progress.percent > 100
      || startupStages.indexOf(progress.stage) < startupStages.indexOf(this.current.stage)) return;
    if (progress.percent === this.current.percent && progress.stage === this.current.stage) return;
    this.current = progress;
    for (const listener of this.listeners) listener();
  };
  complete = () => this.update({ stage: this.current.stage, percent: 100 });
}

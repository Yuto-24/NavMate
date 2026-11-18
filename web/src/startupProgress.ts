export const startupStages = ["authentication", "migration", "runtime", "dependencies", "assets", "application", "projects"] as const;
export type StartupStage = typeof startupStages[number];
export interface StartupProgress { stage: StartupStage; percent: number }
export interface StartupProgressSource {
  getSnapshot(): StartupProgress;
  subscribe(listener: () => void): () => void;
  complete(): void;
  restart(afterMigration?: boolean): void;
}

export const authenticationProgress: StartupProgress = { stage: "authentication", percent: 0 };

// One store per Application, restarted before a new workspace is mounted. Percentages are milestones,
// not elapsed-time estimates; late events cannot move the bar or stage backwards.
export class StartupProgressStore implements StartupProgressSource {
  private offset = 0;
  constructor(private current: StartupProgress = { stage: "runtime", percent: 5 }) {}
  private listeners = new Set<() => void>();
  getSnapshot = () => this.current;
  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  };
  update = (progress: StartupProgress) => {
    progress = { ...progress, percent: this.offset + progress.percent * (100 - this.offset) / 100 };
    if (this.current.percent === 100 || !Number.isFinite(progress.percent) || progress.percent < this.current.percent || progress.percent > 100
      || startupStages.indexOf(progress.stage) < startupStages.indexOf(this.current.stage)) return;
    if (progress.percent === this.current.percent && progress.stage === this.current.stage) return;
    this.current = progress;
    for (const listener of this.listeners) listener();
  };
  complete = () => this.update({ stage: this.current.stage, percent: 100 });
  restart = (afterMigration = false) => {
    // Legacy handover owns 0..40; Local initialization owns the remainder.
    this.offset = afterMigration ? 40 : 0;
    this.current = { stage: "runtime", percent: this.offset + 5 * (100 - this.offset) / 100 };
    for (const listener of this.listeners) listener();
  };
}

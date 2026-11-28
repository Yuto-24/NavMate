import { ApplicationError } from "./application";
import type { ApplicationErrorDetails } from "./application";
import { wrap } from "comlink";
import type { LocalCalculationPhase, LocalWorker } from "./local.worker";
import { startupStages, type StartupProgress } from "./startupProgress";

export class LocalClient {
  private worker = new Worker(new URL("./local.worker.ts", import.meta.url), { type: "module" });
  private remote = wrap<LocalWorker>(this.worker);
  private failed: Promise<never>;
  private terminalError: Error | undefined;
  private fail!: (error: Error) => void;
  private onStartup?: (progress: StartupProgress) => void;

  constructor() {
    this.worker.addEventListener("message", (event: MessageEvent) => {
      const value = event.data;
      if (!this.terminalError && value?.type === "startup-progress"
        && startupStages.includes(value.stage) && Number.isFinite(value.percent)
        && value.percent >= 0 && value.percent <= 100) {
        this.onStartup?.({ stage: value.stage, percent: value.percent });
      }
    });
    this.failed = new Promise((_, reject) => {
      this.fail = (error) => {
        this.terminalError = error;
        this.worker.terminate();
        reject(error);
      };
      this.worker.addEventListener("error", (event) => this.fail(new Error(event.message || "端末内の処理に失敗しました。ページを再読み込みしてください。")));
      this.worker.addEventListener("messageerror", () => this.fail(new Error("端末内計算処理との通信に失敗しました。ページを再読み込みしてください。")));
    });
    void this.failed.catch(() => undefined);
  }

  async request<T>(path: string, body?: unknown, onStartup?: (progress: StartupProgress) => void,
    onCalculationPhase?: (phase: LocalCalculationPhase, percent: number) => void): Promise<T> {
    if (this.terminalError) throw this.terminalError;
    this.onStartup = onStartup;
    // LocalApplication serializes requests. Observe phases only while this request is active.
    const receivePhase = ({ data }: MessageEvent) => {
      if (!this.terminalError && data?.type === "calculation-phase"
        && (data.phase === "weather" || data.phase === "calculation")) onCalculationPhase?.(data.phase, data.percent);
    };
    if (onCalculationPhase) this.worker.addEventListener("message", receivePhase);
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      const json = await Promise.race([
        this.remote.request(path, body),
        this.failed,
        new Promise<never>((_, reject) => {
          timer = setTimeout(() => {
            const error = new Error("端末内の処理がタイムアウトしました。画面を再読み込みしてください。");
            this.fail(error);
            reject(error);
          }, 10 * 60_000);
        }),
      ]);
      const payload = JSON.parse(json) as T | {
        error: { code: string; message: string; details?: ApplicationErrorDetails };
      };
      if (payload && typeof payload === "object" && "error" in payload) {
        const error = payload.error;
        throw new ApplicationError(error.message, error.code, error.details);
      }
      return payload as T;
    } finally {
      clearTimeout(timer);
      if (onCalculationPhase) this.worker.removeEventListener("message", receivePhase);
    }
  }

  dispose() {
    this.fail(new Error("Local session was reset."));
  }
}

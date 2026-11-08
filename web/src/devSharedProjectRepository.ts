import { ApplicationError } from "./application";
import type { LocalAccountContext, LocalProjectRecord, LocalProjectRepository } from "./localProjectRepository";
import type { KeyValueStorage } from "./platform";
import type { SavedProject } from "./types";

const API = "/api/dev-projects";
// User-facing copy confirmed with Gemini CLI.
const unavailable = () => new ApplicationError("サーバーに接続できません。通信状態を確認してください。", "DEV_STORAGE_UNAVAILABLE");
const invalid = () => new ApplicationError("データを読み込めませんでした。元のデータは変更されず保持されています。", "LOCAL_PROJECT_UNAVAILABLE");
const conflict = () => new ApplicationError("他の端末で更新されたため保存できませんでした。一度開き直して最新の内容を確認してください。", "PROJECT_REVISION_CONFLICT");

/** A single online dev workspace. Calculation and portable record validation stay local. */
export class DevSharedProjectRepository implements LocalProjectRepository {
  private initialization?: Promise<void>;
  private importIssues: string[] = [];
  constructor(
    private readonly validate: (record: unknown) => Promise<LocalProjectRecord>,
    private readonly originals: LocalProjectRepository,
    private readonly values: KeyValueStorage,
    private readonly context: LocalAccountContext,
    private readonly transport: typeof fetch = (...args) => fetch(...args),
  ) {}

  private async request(action = "", body?: unknown): Promise<unknown> {
    this.context.assertActive();
    const controller = new AbortController();
    const unsubscribe = this.context.onClose(() => controller.abort());
    const timeout = setTimeout(() => controller.abort(), 15_000);
    try {
      const response = await this.transport(API + (action ? "/" + action : ""), {
        method: body === undefined ? "GET" : "POST", credentials: "same-origin", cache: "no-store",
        headers: { "X-NavMate-Dev-Storage": "1", "Content-Type": "application/json" },
        body: body === undefined ? undefined : JSON.stringify(body), signal: controller.signal,
      });
      this.context.assertActive();
      if (response.status === 409) throw conflict();
      if (!response.ok) throw unavailable();
      const value: unknown = await response.json();
      this.context.assertActive();
      return value;
    } catch (error) {
      this.context.assertActive();
      if (error instanceof ApplicationError) throw error;
      throw unavailable();
    } finally { clearTimeout(timeout); unsubscribe(); }
  }

  private async prepare(): Promise<void> {
    if (!this.initialization) {
      this.initialization = this.copyOriginals().catch(error => {
        this.initialization = undefined;
        throw error;
      });
    }
    await this.initialization;
    this.context.assertActive();
  }

  private async copyOriginals() {
    // Only the anonymous repository is read. Account-owned records never enter this workspace.
    // Originals remain untouched; the server remembers imports after shared deletion.
    let listing: Awaited<ReturnType<LocalProjectRepository["list"]>>;
    let source: string;
    this.importIssues = [];
    try {
      listing = await this.originals.list();
      this.importIssues.push(...listing.unavailable);
      if (!listing.projects.length) return;
      const key = "navmate.dev-shared.import-source";
      source = this.values.getItem(key) ?? crypto.randomUUID();
      this.values.setItem(key, source);
    } catch {
      this.context.assertActive();
      this.importIssues.push("local-import");
      return; // Shared records remain accessible if old browser storage is unavailable.
    }
    for (const project of listing.projects) {
      let record: LocalProjectRecord;
      try { record = await this.originals.read(project.id); }
      catch { this.context.assertActive(); this.importIssues.push(project.id); continue; }
      const result = await this.request("import", { source, record });
      if (!result || typeof result !== "object" || typeof (result as { conflict?: unknown }).conflict !== "boolean") throw unavailable();
      if ((result as { conflict: boolean }).conflict) this.importIssues.push(project.id);
    }
  }

  private async records(): Promise<unknown[]> {
    await this.prepare();
    const value = await this.request();
    if (!value || typeof value !== "object" || !Array.isArray((value as { records?: unknown }).records)) throw unavailable();
    return (value as { records: unknown[] }).records;
  }

  async list() {
    const projects: SavedProject[] = [], tokens: Record<string, string> = {};
    const rows = await this.records();
    const failed = [...this.importIssues];
    for (const raw of rows) {
      try {
        const record = await this.validate(raw);
        this.context.assertActive();
        tokens[record.id] = record.token;
        projects.push({ id: record.id, kind: record.checkpoint ? "SAVED" : "LATEST",
          name: record.checkpoint?.name ?? "Latest", status: record.draft.status,
          revision: record.draft.revision, updatedAt: record.updatedAt });
      } catch { this.context.assertActive(); failed.push(String((raw as { id?: unknown })?.id ?? "unknown")); }
    }
    projects.sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
    return { projects, tokens, unavailable: failed };
  }
  async read(id: string) {
    const raw = (await this.records()).find(row => (row as { id?: unknown })?.id === id);
    try {
      const record = await this.validate(raw);
      this.context.assertActive();
      return record;
    } catch { this.context.assertActive(); throw invalid(); }
  }
  async write(record: LocalProjectRecord, expectedToken: string | null, replaceLatest: boolean) {
    await this.prepare();
    const valid = await this.validate(record);
    await this.request("write", { record: valid, expectedToken, replaceLatest });
  }
  async open(record: LocalProjectRecord, expectedToken = record.token) {
    await this.prepare();
    const valid = await this.validate(record);
    await this.request("open", { record: valid, expectedToken });
  }
  async delete(id: string, expectedToken: string | null) {
    await this.prepare();
    await this.request("delete", { id, expectedToken });
  }
}

/// <reference types="vite/client" />

declare module "*.css";

declare const __LOCAL_MANIFEST_SHA256__: string;
declare const __PYODIDE_VERSION__: string;

interface LocalUnreleasedNotes {
  status: "ready" | "unavailable";
  head: string;
  baseline?: { version: string; commit: string };
  entries: Array<{ number: number; title: string; notes: string }>;
}
declare const __LOCAL_UNRELEASED__: LocalUnreleasedNotes | null;

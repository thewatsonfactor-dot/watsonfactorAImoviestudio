export type Level = "green" | "amber" | "red";
export interface Pill { level: Level; label: string; reason: string; blocking: boolean }
export interface Disk { total_gb: number; free_gb: number; used_gb: number }

export interface Health {
  pills: { engine: Pill; models: Pill; ssd: Pill; memory: Pill };
  can_generate: boolean;
  blocked_reason: string | null;
  queue_blocked_reason: string | null;
  workflow_problems: string[];
  engine: { up: boolean; device: string | null; comfyui_version: string | null; pytorch_version: string | null };
  disk: { internal: Disk | null; ssd: Disk | null };
  memory: { level: string; used_percent: number; total_gb: number; available_gb: number };
  system: { chip: string; memory_gb: number; os: string; python: string };
  stats: { renders_today: number; renders_total: number; avg_render_seconds: number | null };
}

export interface Live {
  stage: string; label: string; step: number | null; total_steps: number | null;
  percent: number; elapsed: number; eta_seconds: number | null;
}

export type JobStatus = "queued" | "running" | "done" | "failed" | "cancelled" | "deleted";
export interface Job {
  id: string; status: JobStatus; created_at: number; started_at: number | null; finished_at: number | null;
  project: string; prompt: string; negative: string | null; preset: string; length: string; seed: number;
  width: number; height: number; frames: number; steps: number; split: number; cfg: number; shift: number;
  input_path: string; output_path: string | null; error: string | null; error_detail: string | null;
  render_seconds: number | null; favorite: boolean; tags: string[]; queue_pos: number | null; parent_id: string | null;
  video_url: string | null; thumb_url: string | null; input_url: string | null; file_exists: boolean;
  live: Live | null;
}

export interface PresetDef {
  label: string; note: string; tier: string; steps: number; split: number; cfg: number; shift: number;
  experimental: boolean; avg_seconds: Record<string, number | null>;
}
export interface Presets {
  fps: number; token_limit: number; token_warn: number;
  lengths: Record<string, { label: string; frames: number; approx: string }>;
  tiers: Record<string, Record<string, [number, number]>>;
  presets: Record<string, PresetDef>;
  negative_default: string;
}

export interface Project { name: string; created_at: number; renders: number }

export interface ModelItem {
  id: string; label: string; folder: string; filename: string; repo: string; repo_path: string;
  size_bytes: number; path: string; state: "present" | "missing" | "wrong_size"; size_on_disk: number;
  download: { state: string; bytes: number; total: number; error: string | null } | null;
}
export interface ModelsStatus { models: ModelItem[]; present: number; total: number; missing_gb: number }

export interface Upload { path: string; width: number; height: number; orientation: string; url: string }

export type Settings = Record<string, string | number | boolean>;

async function req<T>(method: string, url: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method, headers: {} };
  if (body instanceof FormData) init.body = body;
  else if (body !== undefined) {
    init.body = JSON.stringify(body);
    (init.headers as Record<string, string>)["content-type"] = "application/json";
  }
  const r = await fetch(url, init);
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`;
    try {
      const j = await r.json();
      if (j.detail) msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch { /* not json */ }
    throw new Error(msg);
  }
  return r.json() as Promise<T>;
}

export const api = {
  health: () => req<Health>("GET", "/api/health"),
  presets: () => req<Presets>("GET", "/api/presets"),
  projects: () => req<Project[]>("GET", "/api/projects"),
  addProject: (name: string) => req<Project[]>("POST", "/api/projects", { name }),
  settings: () => req<{ settings: Settings; editable: string[] }>("GET", "/api/settings"),
  saveSettings: (s: Settings) => req<{ settings: Settings }>("PUT", "/api/settings", s),
  engine: (action: "start" | "stop" | "restart") => req<{ ok: boolean }>("POST", `/api/engine/${action}`),
  freeMemory: () => req<{ swap_released_mb: number | null; after: { swap_used_mb: number | null; level: string } }>("POST", "/api/engine/free"),
  models: () => req<ModelsStatus>("GET", "/api/models"),
  download: (id: string) => req<unknown>("POST", `/api/models/${id}/download`),
  upload: (file: File) => { const f = new FormData(); f.append("file", file); return req<Upload>("POST", "/api/upload", f); },
  createJob: (body: Record<string, unknown>) => req<Job>("POST", "/api/jobs", body),
  jobs: (scope = "active") => req<Job[]>("GET", `/api/jobs?scope=${scope}`),
  cancel: (id: string) => req<Job>("POST", `/api/jobs/${id}/cancel`),
  dismiss: (id: string) => req<unknown>("POST", `/api/jobs/${id}/dismiss`),
  reorder: (ids: string[]) => req<unknown>("POST", "/api/queue/order", ids),
  library: (q: Record<string, string | boolean | undefined>) => {
    const p = new URLSearchParams();
    Object.entries(q).forEach(([k, v]) => { if (v !== undefined && v !== "" && v !== false) p.set(k, String(v)); });
    return req<Job[]>("GET", `/api/library?${p}`);
  },
  favorite: (id: string, favorite: boolean) => req<Job>("POST", `/api/library/${id}/favorite`, { favorite }),
  reroll: (id: string) => req<Job>("POST", `/api/library/${id}/reroll`),
  remove: (id: string) => req<unknown>("POST", `/api/library/${id}/delete`),
  reveal: (id: string) => req<unknown>("POST", `/api/library/${id}/reveal`),
  rescan: () => req<{ added: number }>("POST", "/api/library/rescan"),
};

/** Rough UMT5 token estimate (English sentencepiece ≈ 1.35 tokens/word). */
export function estimateTokens(text: string): number {
  const words = text.trim().split(/\s+/).filter(Boolean).length;
  const punct = (text.match(/[^\w\s]/g) || []).length;
  return Math.ceil(words * 1.35 + punct * 0.3);
}

export function fmtDuration(sec: number | null | undefined): string {
  if (sec == null || !isFinite(sec)) return "—";
  const s = Math.round(sec);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60), r = s % 60;
  if (m < 60) return r ? `${m}m ${r}s` : `${m}m`;
  return `${Math.floor(m / 60)}h ${m % 60}m`;
}

export function fmtGB(bytes: number): string {
  return `${(bytes / 1e9).toFixed(bytes > 1e10 ? 0 : 1)} GB`;
}

export function timeAgo(ts: number | null): string {
  if (!ts) return "";
  const d = Date.now() / 1000 - ts;
  if (d < 60) return "just now";
  if (d < 3600) return `${Math.floor(d / 60)} min ago`;
  if (d < 86400) return `${Math.floor(d / 3600)} h ago`;
  return new Date(ts * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export function orientationOf(w: number, h: number): string {
  const r = w / Math.max(h, 1);
  return r > 1.15 ? "landscape" : r < 0.87 ? "portrait" : "square";
}

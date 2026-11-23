export type Level = "green" | "amber" | "red";
export interface Pill { level: Level; label: string; reason: string; blocking: boolean }
export interface Disk { total_gb: number; free_gb: number; used_gb: number }

export interface Health {
  pills: { engine: Pill; models: Pill; ssd: Pill; memory: Pill };
  can_generate: boolean;
  blocked_reason: string | null;
  queue_blocked_reason: string | null;
  workflow_problems: string[];
  image: { ready: boolean; reason: string | null; present: number; total: number; missing_gb: number; workflow_problems: string[] };
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

export type JobKind = "video" | "image";
export type JobStatus = "queued" | "running" | "done" | "failed" | "cancelled" | "deleted";
export interface Job {
  id: string; kind: JobKind; refs: string[]; ref_urls: (string | null)[]; status: JobStatus; created_at: number; started_at: number | null; finished_at: number | null;
  project: string; prompt: string; negative: string | null; preset: string; length: string; seed: number;
  width: number; height: number; frames: number; steps: number; split: number; cfg: number; shift: number;
  input_path: string; output_path: string | null; error: string | null; error_detail: string | null;
  render_seconds: number | null; favorite: boolean; tags: string[]; queue_pos: number | null; parent_id: string | null; finish?: string;
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
  image: { sizes: Record<string, [number, number]>; steps: number; cfg: number; shift: number; max_refs: number; note: string; avg_seconds: number | null };
  negative_default: string;
  finishes?: Record<string, { label: string; note: string }>;
}

// ---- LENS: stage templates + per-project look locks (studio/config/lens.json)
export interface LensField { id: string; label: string; placeholder?: string; default: string; options?: string[] }
export interface LensStage {
  id: string; label: string; kind: "image" | "video"; aspect?: string; copy_only?: boolean;
  locks: ("realism" | "lens" | "lighting" | "shadow_side")[]; tips: string[]; fields: LensField[]; template: string;
}
export interface LensFix { id: string; problem: string; fix: string; add: string }
export interface LensLocks {
  realism_on?: boolean; lens_on?: boolean; lens_text?: string; lighting_on?: boolean; lighting_text?: string;
  shadow_on?: boolean; finish?: string;
}
export interface Lens {
  locks: { realism: string; realism_video: string; lens: string; shadow_side: string; lighting_example: string };
  lock_help: Record<string, string>;
  stages: LensStage[]; fixes: LensFix[];
  projects: Record<string, LensLocks>;
}
export const LOCK_DEFAULTS: Required<Omit<LensLocks, "lens_text" | "lighting_text" | "finish">> = {
  realism_on: true, lens_on: false, lighting_on: false, shadow_on: false,
};

/** Fill a stage template: each {field} takes what was typed, or the field's default. */
export function fillTemplate(stage: LensStage, values: Record<string, string>): string {
  return stage.template.replace(/\{(\w+)\}/g, (_, id: string) => {
    const f = stage.fields.find(x => x.id === id);
    return (values[id] || "").trim() || f?.default || "";
  }).replace(/\s+/g, " ").trim();
}

/** The lock text appended to every prompt, in a fixed order: realism, lens, lighting, shadow side.
 *  With a stage picked, only the locks that stage allows apply (character sheets stay evenly lit). */
export function lockText(lens: Lens | null, locks: LensLocks, kind: "image" | "video", stage?: LensStage | null): string {
  if (!lens) return "";
  const allowed = (k: string) => !stage || (stage.locks as string[]).includes(k);
  const l = { ...LOCK_DEFAULTS, ...locks };
  const out: string[] = [];
  if (l.realism_on && allowed("realism")) out.push(kind === "video" ? lens.locks.realism_video : lens.locks.realism);
  if (l.lens_on && allowed("lens")) out.push((locks.lens_text || "").trim() || lens.locks.lens);
  if (l.lighting_on && allowed("lighting") && (locks.lighting_text || "").trim()) out.push(locks.lighting_text!.trim());
  if (l.shadow_on && allowed("shadow_side")) out.push(lens.locks.shadow_side);
  return out.join(" ");
}

export interface Forecast {
  level: "ok" | "untested" | "failed"; tokens: number; proven_tokens: number | null; failed_tokens: number | null; message: string;
}

export interface Project { name: string; created_at: number; renders: number }

export interface ModelItem {
  id: string; group: "video" | "image"; label: string; folder: string; filename: string; repo: string; repo_path: string;
  size_bytes: number; path: string; state: "present" | "missing" | "wrong_size"; size_on_disk: number;
  download: { state: string; bytes: number; total: number; error: string | null } | null;
}
export interface GroupStatus { present: number; total: number; missing_gb: number }
export interface ModelsStatus { models: ModelItem[]; present: number; total: number; missing_gb: number; groups: Record<string, GroupStatus> }

export interface Upload { path: string; width: number; height: number; orientation: string; url: string }

export type Settings = Record<string, string | number | boolean>;

export interface PromptBlock { id: string; label: string; text: string; group?: string; custom?: boolean }
export interface PromptCategory { id: string; label: string; options: PromptBlock[] }
export type PromptLibrary = Record<"video" | "image", PromptCategory[]>;
export type Picks = Record<string, string>; // category id -> block id

/** The prompt the engine actually reads: what the user typed, then each picked block, in category order. */
export function composePrompt(base: string | string[], cats: PromptCategory[] | undefined, picks: Picks): string {
  const parts: string[] = [];
  for (const raw of Array.isArray(base) ? base : [base]) {
    const b = raw.trim();
    if (b) parts.push(/[.!?]$/.test(b) ? b : `${b}.`);
  }
  for (const c of cats ?? []) {
    const o = c.options.find(x => x.id === picks[c.id]);
    if (o) parts.push(o.text.trim());
  }
  return parts.join(" ");
}

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
  forecast: (w: number, h: number, frames: number) => req<Forecast>("GET", `/api/forecast?width=${w}&height=${h}&frames=${frames}`),
  addProject: (name: string) => req<Project[]>("POST", "/api/projects", { name }),
  settings: () => req<{ settings: Settings; editable: string[] }>("GET", "/api/settings"),
  saveSettings: (s: Settings) => req<{ settings: Settings }>("PUT", "/api/settings", s),
  engine: (action: "start" | "stop" | "restart") => req<{ ok: boolean }>("POST", `/api/engine/${action}`),
  freeMemory: () => req<{ swap_released_mb: number | null; after: { swap_used_mb: number | null; level: string } }>("POST", "/api/engine/free"),
  models: () => req<ModelsStatus>("GET", "/api/models"),
  download: (id: string) => req<unknown>("POST", `/api/models/${id}/download`),
  upload: (file: File) => { const f = new FormData(); f.append("file", file); return req<Upload>("POST", "/api/upload", f); },
  createJob: (body: Record<string, unknown>) => req<Job>("POST", "/api/jobs", body),
  createImage: (body: { prompt: string; refs: string[]; aspect?: string; project?: string; seed?: number | null; negative?: string }) =>
    req<Job>("POST", "/api/images", body),
  toKeyframe: (id: string) => req<Upload>("POST", `/api/library/${id}/to-keyframe`),
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
  promptLibrary: () => req<PromptLibrary>("GET", "/api/prompt-library"),
  addBlock: (b: { kind: "video" | "image"; category: string; label: string; text: string }) =>
    req<PromptLibrary>("POST", "/api/prompt-library/blocks", b),
  deleteBlock: (id: string) => req<PromptLibrary>("DELETE", `/api/prompt-library/blocks/${id}`),
  rescan: () => req<{ added: number }>("POST", "/api/library/rescan"),
  lens: () => req<Lens>("GET", "/api/lens"),
  saveLens: (project: string, locks: LensLocks) => req<Lens>("PUT", `/api/lens/projects/${encodeURIComponent(project)}`, locks),
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

/** What a job is, in the words the UI uses: "Standard · 81f" for video, "Image · still" for a picture. */
export function jobTag(j: Job, presets: Presets | null): string {
  if (j.kind === "image") return `Image · ${j.refs.length ? `${j.refs.length} ref${j.refs.length > 1 ? "s" : ""}` : "text only"}`;
  return `${presets?.presets[j.preset]?.label ?? j.preset} · ${j.frames}f`;
}

/** Library/Renders "try again" for an image job: back to the Image screen with the same references. */
export function imageDraftFrom(j: Job) {
  return {
    kind: "image" as const, prompt: j.prompt, project: j.project, aspect: orientationOf(j.width, j.height),
    refs: j.refs.map((path, i) => ({ path, url: j.ref_urls[i] ?? "", width: 0, height: 0, orientation: "" })).filter(r => r.url),
  };
}

export function orientationOf(w: number, h: number): string {
  const r = w / Math.max(h, 1);
  return r >= 2 ? "scope" : r > 1.15 ? "landscape" : r < 0.87 ? "portrait" : "square";
}

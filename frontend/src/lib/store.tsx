import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, type Health, type Job, type Presets, type Project } from "./api";

export type Route = "image" | "create" | "renders" | "library" | "models" | "settings";
export interface Toast { id: number; kind: "ok" | "error" | "info"; text: string }
export interface Draft {
  /** "image" drafts are for the Image screen; anything else pre-fills Create. */
  kind?: "image" | "video";
  upload?: { path: string; url: string; width: number; height: number; orientation: string };
  refs?: { path: string; url: string; width: number; height: number; orientation: string }[];
  aspect?: string;
  prompt?: string; negative?: string; project?: string; preset?: string; length?: string; seed?: number | null;
}

interface Ctx {
  route: Route; go: (r: Route) => void;
  health: Health | null; refreshHealth: () => void;
  presets: Presets | null; refreshPresets: () => void;
  projects: Project[]; refreshProjects: () => void;
  jobs: Record<string, Job>; queueIds: string[]; queueBlocked: string | null;
  libraryVersion: number;
  toasts: Toast[]; toast: (text: string, kind?: Toast["kind"]) => void;
  draft: Draft | null; setDraft: (d: Draft | null) => void;
  connected: boolean;
  forget: (id: string) => void;
}

const StudioContext = createContext<Ctx | null>(null);

export function StudioProvider({ children }: { children: ReactNode }) {
  const [route, setRoute] = useState<Route>(() => (location.hash.slice(1) as Route) || "create");
  const [health, setHealth] = useState<Health | null>(null);
  const [presets, setPresets] = useState<Presets | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [jobs, setJobs] = useState<Record<string, Job>>({});
  const [queueIds, setQueueIds] = useState<string[]>([]);
  const [queueBlocked, setQueueBlocked] = useState<string | null>(null);
  const [libraryVersion, setLibraryVersion] = useState(0);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [connected, setConnected] = useState(false);
  const toastId = useRef(0);

  const go = useCallback((r: Route) => { setRoute(r); location.hash = r; }, []);
  useEffect(() => {
    const on = () => setRoute(((location.hash.slice(1) as Route) || "create"));
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);

  const forget = useCallback((id: string) => setJobs(prev => { const n = { ...prev }; delete n[id]; return n; }), []);

  const toast = useCallback((text: string, kind: Toast["kind"] = "ok") => {
    const id = ++toastId.current;
    setToasts(t => [...t, { id, kind, text }]);
    setTimeout(() => setToasts(t => t.filter(x => x.id !== id)), kind === "error" ? 7000 : 3500);
  }, []);

  const refreshHealth = useCallback(() => { api.health().then(setHealth).catch(() => setHealth(null)); }, []);
  const refreshPresets = useCallback(() => { api.presets().then(setPresets).catch(() => {}); }, []);
  const refreshProjects = useCallback(() => { api.projects().then(setProjects).catch(() => {}); }, []);
  const refreshJobs = useCallback(() => {
    api.jobs("active").then(list => {
      setJobs(prev => {
        const next = { ...prev };
        list.forEach(j => { next[j.id] = j; });
        return next;
      });
      setQueueIds(list.filter(j => j.status === "queued").sort((a, b) => (a.queue_pos ?? 0) - (b.queue_pos ?? 0)).map(j => j.id));
    }).catch(() => {});
  }, []);

  useEffect(() => {
    refreshHealth(); refreshPresets(); refreshProjects(); refreshJobs();
    const t = setInterval(refreshHealth, 4000);
    return () => clearInterval(t);
  }, [refreshHealth, refreshPresets, refreshProjects, refreshJobs]);

  // Live events from the Studio backend.
  useEffect(() => {
    let ws: WebSocket | null = null;
    let stop = false;
    let retry: ReturnType<typeof setTimeout>;
    // Back off while the Studio is down (1.5 s doubling to 30 s) instead of retrying every 1.5 s forever.
    let delay = 1500;
    const connect = () => {
      ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/ws`);
      ws.onopen = () => { delay = 1500; setConnected(true); refreshJobs(); };
      ws.onclose = () => {
        setConnected(false);
        if (stop) return;
        retry = setTimeout(connect, delay);
        delay = Math.min(delay * 2, 30000);
      };
      ws.onmessage = ev => {
        const msg = JSON.parse(ev.data);
        if (msg.type === "job" && msg.job) {
          const j: Job = msg.job;
          setJobs(prev => ({ ...prev, [j.id]: j }));
          if (j.status === "done") { refreshPresets(); refreshProjects(); }
        } else if (msg.type === "queue") {
          setQueueIds(msg.ids); setQueueBlocked(msg.blocked_reason);
        } else if (msg.type === "library_changed") {
          setLibraryVersion(v => v + 1);
        }
      };
    };
    connect();
    return () => { stop = true; clearTimeout(retry); ws?.close(); };
  }, [refreshJobs, refreshPresets, refreshProjects]);

  const value = useMemo<Ctx>(() => ({
    route, go, health, refreshHealth, presets, refreshPresets, projects, refreshProjects,
    jobs, queueIds, queueBlocked, libraryVersion, toasts, toast, draft, setDraft, connected, forget,
  }), [route, go, health, refreshHealth, presets, refreshPresets, projects, refreshProjects,
       jobs, queueIds, queueBlocked, libraryVersion, toasts, toast, draft, connected, forget]);

  return <StudioContext.Provider value={value}>{children}</StudioContext.Provider>;
}

export function useStudio(): Ctx {
  const c = useContext(StudioContext);
  if (!c) throw new Error("useStudio outside provider");
  return c;
}

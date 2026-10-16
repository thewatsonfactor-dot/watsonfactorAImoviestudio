import { Clapperboard, Film, HardDrive, Library, PanelLeftClose, PanelLeftOpen, Settings, Sparkles } from "lucide-react";
import { useState, type ReactNode } from "react";
import type { Level, Pill } from "../lib/api";
import { useStudio, type Route } from "../lib/store";

const NAV: { id: Route; label: string; icon: typeof Sparkles }[] = [
  { id: "create", label: "Create", icon: Sparkles },
  { id: "renders", label: "Renders", icon: Clapperboard },
  { id: "library", label: "Library", icon: Library },
  { id: "models", label: "Models", icon: HardDrive },
  { id: "settings", label: "Settings", icon: Settings },
];

const TITLES: Record<Route, [string, string]> = {
  create: ["Create", "Keyframe in. Motion out."],
  renders: ["Renders", "What the engine is working on"],
  library: ["Library", "Every render, by project"],
  models: ["Models", "What the engine needs on the SSD"],
  settings: ["Settings", "Paths, engine and system"],
};

export function Shell({ children }: { children: ReactNode }) {
  const { route, go, jobs, queueIds } = useStudio();
  const [collapsed, setCollapsed] = useState(false);
  const active = Object.values(jobs).filter(j => j.status === "running").length + queueIds.length;

  return (
    <div className="flex h-full">
      <aside className={`flex shrink-0 flex-col border-r border-hairline bg-rail transition-[width] duration-200 ${collapsed ? "w-[76px]" : "w-[252px]"}`}>
        <div className={`flex items-center ${collapsed ? "justify-center px-2 pt-5 pb-4" : "px-5 pt-6 pb-5"}`}>
          {collapsed
            ? <img src="/brand/wf-mark-tight.png" alt="Watson Factor" className="h-11 w-11" />
            : <img src="/brand/wf-lockup-studio.png" alt="The Watson Factor — AI Studio" className="w-full" />}
        </div>
        <nav className="flex flex-1 flex-col gap-1 px-3 pt-2">
          {NAV.map(n => {
            const on = route === n.id;
            const Icon = n.icon;
            return (
              <button key={n.id} onClick={() => go(n.id)} title={n.label}
                className={`group relative flex items-center gap-3 rounded-[3px] py-2.5 text-[15px] transition-colors ${collapsed ? "justify-center px-0" : "px-3"} ${on ? "bg-surface-2 text-ink" : "text-ink-2 hover:bg-surface hover:text-ink"}`}>
                {on && <span className="wf-grad-bg absolute top-1.5 bottom-1.5 left-0 w-[3px] rounded-full" />}
                <Icon size={18} className={on ? "text-accent" : "text-muted group-hover:text-ink-2"} />
                {!collapsed && <span className={on ? "font-semibold" : ""}>{n.label}</span>}
                {n.id === "renders" && active > 0 && (
                  <span className={`wf-grad-bg rounded-full px-1.5 text-[11px] font-bold text-on-accent ${collapsed ? "absolute top-1 right-2" : "ml-auto"}`}>{active}</span>
                )}
              </button>
            );
          })}
        </nav>
        <div className="px-3 pb-4">
          <button onClick={() => setCollapsed(c => !c)} className="btn btn-ghost w-full" title={collapsed ? "Expand" : "Collapse"}>
            {collapsed ? <PanelLeftOpen size={16} /> : <><PanelLeftClose size={16} /><span className="text-xs">Collapse</span></>}
          </button>
          {!collapsed && <p className="mt-2 px-2 font-mono text-[10px] tracking-wider text-muted">LOCAL · 127.0.0.1 · v1.0</p>}
        </div>
      </aside>
      <main className="wf-glow flex min-w-0 flex-1 flex-col">
        <TopBar />
        <div className="scroll-thin flex-1 overflow-y-auto">{children}</div>
      </main>
    </div>
  );
}

const DOT: Record<Level, string> = { green: "bg-ok", amber: "bg-warn", red: "bg-bad" };

function StatusPill({ pill }: { pill: Pill }) {
  return (
    <div className="group relative">
      <div className={`flex items-center gap-2 rounded-full border px-3 py-1.5 text-[13px] ${pill.level === "red" ? "border-bad/40 bg-bad/10" : pill.level === "amber" ? "border-warn/35 bg-warn/5" : "border-hairline bg-surface"}`}>
        <span className={`h-2 w-2 rounded-full ${DOT[pill.level]} ${pill.level !== "green" ? "animate-pulse" : ""}`} />
        <span className="text-ink-2">{pill.label}</span>
      </div>
      <div className="pointer-events-none absolute top-full right-0 z-50 mt-2 w-72 rounded-[3px] border border-hairline bg-surface-2 p-3 text-[13px] leading-snug text-ink-2 opacity-0 shadow-2xl transition-opacity group-hover:opacity-100">
        {pill.reason}
      </div>
    </div>
  );
}

function TopBar() {
  const { route, health, connected } = useStudio();
  const [title, sub] = TITLES[route];
  const offline: Pill = { level: "red", label: "Studio", reason: "Can't reach the Studio backend. Relaunch the app.", blocking: true };
  return (
    <header className="sticky top-0 z-30 bg-ground/80 backdrop-blur">
      <div className="flex items-end justify-between gap-6 px-10 pt-7 pb-5">
        <div>
          <p className="eyebrow mb-2">{sub}</p>
          <h1 className="display text-[44px]">{title}</h1>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2 pb-1">
          {!connected && !health && <StatusPill pill={offline} />}
          {health && (["engine", "models", "ssd", "memory"] as const).map(k => <StatusPill key={k} pill={health.pills[k]} />)}
        </div>
      </div>
      <div className="wf-hairline-grad" />
    </header>
  );
}

export function Toasts() {
  const { toasts } = useStudio();
  return (
    <div className="pointer-events-none fixed top-[132px] right-8 z-[100] flex flex-col items-end gap-2">
      {toasts.map(t => (
        <div key={t.id} className={`pointer-events-auto max-w-sm rounded-[3px] border px-4 py-3 text-sm shadow-2xl ${t.kind === "error" ? "border-bad/50 bg-[#2a0f22] text-ink" : "border-hairline bg-surface-2 text-ink"}`}>
          {t.kind === "ok" && <Film size={14} className="mr-2 inline text-accent" />}{t.text}
        </div>
      ))}
    </div>
  );
}

import { Search, X } from "lucide-react";
import { useMemo, useState } from "react";
import type { PromptBlock } from "../lib/api";

/** Visual camera-move picker: cards with a tiny animated diagram of each move, group tabs and search.
 *  The diagram is a "frame" (what the camera sees) moving over a scene with a subject dot. */

// Which diagram animation each move uses. Unknown ids (Daniel's own blocks) fall back to "custom".
const ANIM: Record<string, string> = {
  static: "still", locked: "still", time_lapse: "timelapse", tilt_shift: "still",
  pan_right: "pan-r", pan_left: "pan-l", whip_pan_right: "whip-r", whip_pan_left: "whip-l",
  tilt_up: "tilt-u", tilt_down: "tilt-d",
  slow_zoom_in: "zoom-in", fast_zoom_in: "zoom-in-fast", crash_zoom_in: "zoom-in-crash", infinite_zoom: "zoom-in",
  slow_zoom_out: "zoom-out", fast_zoom_out: "zoom-out-fast", crash_zoom_out: "zoom-out-crash", earth_zoom_out: "zoom-out-crash",
  dolly_in: "zoom-in", drone_push_in: "zoom-in", push_past: "zoom-in", pass_through: "zoom-in-fast", fpv: "zoom-in",
  dolly_out: "zoom-out", drone_pull_back: "zoom-out",
  tracking: "track", side_tracking: "track", low_tracking: "track-low", vehicle_tracking: "track", chase: "chase",
  follow: "track", reverse_tracking: "track",
  truck_right: "pan-r", truck_left: "pan-l", slider_right: "slide-r", slider_left: "slide-l",
  pedestal_up: "tilt-u", pedestal_down: "tilt-d", crane_up: "tilt-u", crane_down: "tilt-d", helicopter: "pan-r",
  arc_right: "arc-r", arc_left: "arc-l", orbit_cw: "orbit-r", orbit_ccw: "orbit-l",
  handheld: "shake", snorricam: "shake", handheld_follow: "shake", documentary: "shake",
};

const CSS = `
@keyframes wfm-pan-r { 0%,15% { transform: translateX(-30%) } 85%,100% { transform: translateX(30%) } }
@keyframes wfm-pan-l { 0%,15% { transform: translateX(30%) } 85%,100% { transform: translateX(-30%) } }
@keyframes wfm-whip-r { 0%,55% { transform: translateX(-30%); filter: blur(0) } 70% { filter: blur(2px) } 80%,100% { transform: translateX(30%); filter: blur(0) } }
@keyframes wfm-whip-l { 0%,55% { transform: translateX(30%); filter: blur(0) } 70% { filter: blur(2px) } 80%,100% { transform: translateX(-30%); filter: blur(0) } }
@keyframes wfm-tilt-u { 0%,15% { transform: translateY(28%) } 85%,100% { transform: translateY(-28%) } }
@keyframes wfm-tilt-d { 0%,15% { transform: translateY(-28%) } 85%,100% { transform: translateY(28%) } }
@keyframes wfm-zoom-in { 0%,15% { transform: scale(1) } 85%,100% { transform: scale(.45) } }
@keyframes wfm-zoom-out { 0%,15% { transform: scale(.45) } 85%,100% { transform: scale(1) } }
@keyframes wfm-slide-r { 0%,15% { transform: translateX(-12%) } 85%,100% { transform: translateX(12%) } }
@keyframes wfm-slide-l { 0%,15% { transform: translateX(12%) } 85%,100% { transform: translateX(-12%) } }
@keyframes wfm-orbit { from { transform: rotate(0) } to { transform: rotate(360deg) } }
@keyframes wfm-arc { 0%,15% { transform: rotate(0) } 85%,100% { transform: rotate(var(--wfm-arc)) } }
@keyframes wfm-shake { 0%,100% { transform: translate(0,0) rotate(0) } 25% { transform: translate(2px,-1px) rotate(1deg) } 50% { transform: translate(-1px,2px) rotate(-1deg) } 75% { transform: translate(-2px,-1px) rotate(.5deg) } }
@keyframes wfm-subject-run { 0% { transform: translateX(-38px) } 100% { transform: translateX(38px) } }
@keyframes wfm-blink { 0%,100% { opacity: 1 } 50% { opacity: .35 } }
`;

function Diagram({ kind, active }: { kind: string; active: boolean }) {
  const play = active ? "running" : "paused";
  const frame: React.CSSProperties = { animationPlayState: play, animationIterationCount: "infinite", animationTimingFunction: "ease-in-out" };
  let frameAnim: React.CSSProperties = {};
  let wrap: React.CSSProperties = {};
  let subject: React.CSSProperties = {};
  const dur = (s: number) => ({ animationDuration: `${s}s` });
  switch (kind) {
    case "pan-r": case "pan-l": case "tilt-u": case "tilt-d": case "slide-r": case "slide-l":
    case "zoom-in": case "zoom-out":
      frameAnim = { animationName: `wfm-${kind}`, ...dur(2.4), animationDirection: "alternate" }; break;
    case "zoom-in-fast": frameAnim = { animationName: "wfm-zoom-in", ...dur(1.1), animationDirection: "alternate" }; break;
    case "zoom-out-fast": frameAnim = { animationName: "wfm-zoom-out", ...dur(1.1), animationDirection: "alternate" }; break;
    case "zoom-in-crash": frameAnim = { animationName: "wfm-zoom-in", ...dur(0.7), animationDirection: "alternate", animationTimingFunction: "cubic-bezier(.8,0,.2,1)" }; break;
    case "zoom-out-crash": frameAnim = { animationName: "wfm-zoom-out", ...dur(0.7), animationDirection: "alternate", animationTimingFunction: "cubic-bezier(.8,0,.2,1)" }; break;
    case "whip-r": case "whip-l": frameAnim = { animationName: `wfm-${kind}`, ...dur(1.6), animationDirection: "alternate" }; break;
    case "arc-r": case "arc-l":
      wrap = { animationName: "wfm-arc", ...dur(2.6), animationDirection: "alternate", ["--wfm-arc" as string]: kind === "arc-r" ? "70deg" : "-70deg" }; break;
    case "orbit-r": case "orbit-l":
      wrap = { animationName: "wfm-orbit", ...dur(4), animationTimingFunction: "linear", animationDirection: kind === "orbit-r" ? "normal" : "reverse" }; break;
    case "shake": frameAnim = { animationName: "wfm-shake", ...dur(0.5), animationTimingFunction: "linear" }; break;
    case "track": case "track-low": case "chase":
      subject = { animationName: "wfm-subject-run", ...dur(kind === "chase" ? 1.1 : 2.6), animationTimingFunction: "linear", animationIterationCount: "infinite", animationDirection: "alternate", animationPlayState: play };
      frameAnim = { animationName: "wfm-subject-run", ...dur(kind === "chase" ? 1.1 : 2.6), animationTimingFunction: "linear", animationDirection: "alternate" };
      break;
    case "timelapse": subject = { animationName: "wfm-blink", ...dur(0.6), animationIterationCount: "infinite", animationPlayState: play }; break;
    default: break;
  }
  const isArc = kind.startsWith("arc") || kind.startsWith("orbit");
  return (
    <div className="relative h-[54px] w-full overflow-hidden rounded-[2px] bg-[#030820]">
      {/* scene: horizon + a few "buildings" */}
      <div className="absolute inset-x-0 bottom-[30%] h-px bg-hairline" />
      <div className="absolute bottom-[30%] left-[12%] h-3 w-2 bg-surface-2" />
      <div className="absolute bottom-[30%] right-[14%] h-5 w-3 bg-surface-2" />
      <div className={`absolute left-1/2 -ml-[3px] h-[10px] w-[6px] rounded-full bg-pink ${kind === "track-low" ? "bottom-[30%]" : "bottom-[30%]"}`} style={subject} />
      {isArc ? (
        <div className="absolute top-1/2 left-1/2 h-0 w-0" style={{ ...frame, ...wrap }}>
          <div className="absolute -top-[4px] left-[18px] h-[8px] w-[11px] rounded-[1px] border border-accent" />
        </div>
      ) : (
        <div className={`absolute ${kind === "track-low" ? "top-[42%] h-[46%]" : "top-[14%] h-[72%]"} left-[22%] w-[56%] rounded-[2px] border border-accent`}
          style={{ ...frame, ...frameAnim }} />
      )}
    </div>
  );
}

export function MovePicker({ options, value, onChange }: { options: PromptBlock[]; value: string | undefined; onChange: (id: string | undefined) => void }) {
  const groups = useMemo(() => [...new Set(options.map(o => o.group ?? "Other"))], [options]);
  const [group, setGroup] = useState<string>("All");
  const [q, setQ] = useState("");
  const [hover, setHover] = useState<string | null>(null);
  const shown = options.filter(o => (group === "All" || (o.group ?? "Other") === group)
    && (!q || o.label.toLowerCase().includes(q.toLowerCase())));
  const picked = options.find(o => o.id === value);
  return (
    <div>
      <style>{CSS}</style>
      <div className="mb-2 flex items-center justify-between gap-3">
        <span className="text-[12px] text-muted">Camera move{picked ? <> · <span className="text-ink">{picked.label}</span></> : ""}</span>
        <div className="flex items-center gap-1.5">
          {picked && <button className="btn btn-ghost px-2 py-1 text-[11px]" onClick={() => onChange(undefined)}><X size={12} />None</button>}
          <div className="relative w-40">
            <Search size={13} className="absolute top-1/2 left-2.5 -translate-y-1/2 text-muted" />
            <input className="field py-1.5 pl-7 text-[12px]" placeholder="Search moves" value={q} onChange={e => setQ(e.target.value)} />
          </div>
        </div>
      </div>
      <div className="scroll-thin mb-2 flex gap-1 overflow-x-auto pb-1">
        {["All", ...groups].map(g => (
          <button key={g} onClick={() => setGroup(g)}
            className={`shrink-0 rounded-full border px-2.5 py-1 text-[11px] ${group === g ? "border-accent bg-accent/10 text-ink" : "border-hairline text-ink-2 hover:border-accent/50"}`}>{g}</button>
        ))}
      </div>
      <div className="scroll-thin grid max-h-[300px] grid-cols-3 gap-2 overflow-y-auto pr-1 sm:grid-cols-4">
        {shown.map(o => {
          const on = o.id === value;
          return (
            <button key={o.id} title={o.text} onClick={() => onChange(on ? undefined : o.id)}
              onMouseEnter={() => setHover(o.id)} onMouseLeave={() => setHover(null)}
              className={`rounded-[3px] p-1.5 text-left transition-colors ${on ? "wf-grad-border" : "border border-hairline bg-ground hover:border-accent/50"}`}>
              <Diagram kind={ANIM[o.id] ?? (o.custom ? "still" : "still")} active={on || hover === o.id} />
              <span className="mt-1 block truncate text-[11px] leading-tight text-ink-2">{o.label}</span>
            </button>
          );
        })}
        {shown.length === 0 && <p className="col-span-full py-4 text-center text-[12px] text-muted">No moves match.</p>}
      </div>
    </div>
  );
}

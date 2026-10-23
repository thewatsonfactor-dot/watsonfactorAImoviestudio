import { AlertTriangle, Clapperboard, Dice5, ImagePlus, Lock, Plus, Unlock, UserPlus, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, composePrompt, fmtDuration, orientationOf, timeAgo, type Job, type Picks, type PromptCategory, type Upload } from "../lib/api";
import { useStudio } from "../lib/store";
import { Section } from "../components/ui";
import { PromptBuilder } from "../components/PromptBuilder";

const LS = "wfstudio.image";
function remember(): Record<string, string> {
  try { return JSON.parse(localStorage.getItem(LS) || "{}"); } catch { return {}; }
}
function save(v: Record<string, string>) {
  try { localStorage.setItem(LS, JSON.stringify({ ...remember(), ...v })); } catch { /* storage unavailable */ }
}

type Ref = Pick<Upload, "path" | "url" | "width" | "height" | "orientation">;
const SHAPES: [string, string][] = [["landscape", "Landscape"], ["portrait", "Portrait"], ["square", "Square"]];

export default function ImagePage() {
  const { health, presets, projects, refreshProjects, toast, go, draft, setDraft, jobs, queueIds, libraryVersion } = useStudio();
  const mem = remember();
  const [refs, setRefs] = useState<(Ref | null)[]>([null, null, null]);
  const [busySlot, setBusySlot] = useState<number | null>(null);
  const [dragSlot, setDragSlot] = useState<number | null>(null);
  const [prompt, setPrompt] = useState("");
  const [picks, setPicks] = useState<Picks>({});
  const [recipe, setRecipe] = useState<PromptCategory[]>([]);
  // Film stills are landscape; character photos are usually portrait headshots, so the shape
  // deliberately does NOT follow Picture 1. Remembered between visits.
  const [aspect, setAspect] = useState<string>(mem.aspect || "landscape");
  const [project, setProject] = useState(mem.project || "");
  const [newProject, setNewProject] = useState<string | null>(null);
  const [seedLocked, setSeedLocked] = useState(false);
  const [seed, setSeed] = useState<number>(() => Math.floor(Math.random() * 2 ** 32));
  const [submitting, setSubmitting] = useState(false);
  const [recent, setRecent] = useState<Job[]>([]);
  const fileRef = useRef<HTMLInputElement>(null);
  const pickSlot = useRef(0);

  // Remix / Try again / Use as reference from the Library pre-fill this screen.
  useEffect(() => {
    if (!draft || draft.kind !== "image") return;
    if (draft.refs) setRefs([0, 1, 2].map(i => draft.refs![i] ?? null));
    if (draft.prompt != null) setPrompt(draft.prompt);
    if (draft.project) setProject(draft.project);
    if (draft.aspect) setAspect(draft.aspect);
    if (draft.seed != null) { setSeed(draft.seed); setSeedLocked(true); }
    setDraft(null);
  }, [draft, setDraft]);

  useEffect(() => {
    if (mem.project) return;
    api.settings().then(({ settings: s }) => setProject(p => p || String(s.default_project))).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    api.library({ kind: "image" }).then(list => setRecent(list.slice(0, 8))).catch(() => {});
  }, [libraryVersion]);

  const onFile = useCallback(async (file: File | undefined | null, slot: number) => {
    if (!file) return;
    if (!/^image\/(png|jpe?g|webp)$/.test(file.type)) { toast("Use a PNG, JPG or WEBP image.", "error"); return; }
    setBusySlot(slot);
    try {
      const up = await api.upload(file);
      setRefs(r => r.map((x, i) => (i === slot ? up : x)));
    } catch (e) { toast((e as Error).message, "error"); }
    finally { setBusySlot(null); }
  }, [toast]);

  // Paste fills the first empty slot.
  useEffect(() => {
    const onPaste = (e: ClipboardEvent) => {
      const item = [...(e.clipboardData?.items || [])].find(i => i.type.startsWith("image/"));
      if (!item) return;
      const slot = refs.findIndex(r => r === null);
      if (slot === -1) { toast("All three reference slots are full — remove one first.", "info"); return; }
      onFile(item.getAsFile(), slot);
    };
    window.addEventListener("paste", onPaste);
    return () => window.removeEventListener("paste", onPaste);
  }, [onFile, refs, toast]);

  if (!presets) return <div className="p-10 text-muted">Loading…</div>;
  const ip = presets.image;
  if (!ip) return <div className="p-10 text-muted">This Studio's presets have no image section — update the Studio.</div>;

  const filled = refs.filter((r): r is Ref => r !== null);
  const shape = ip.sizes[aspect] ? aspect : "landscape";
  const [w, h] = ip.sizes[shape];
  const running = Object.values(jobs).find(j => j.kind === "image" && j.status === "running");
  const ahead = queueIds.length + Object.values(jobs).filter(j => j.status === "running").length;
  const projectName = newProject !== null ? newProject.trim() : project;

  const blocked = !health ? "Can't reach the Studio backend." : health.image?.reason ?? null;
  const fullPrompt = composePrompt(prompt, recipe, picks);
  const missing = !fullPrompt.trim() ? "Describe the image." : !projectName ? "Pick a project." : null;
  const reason = blocked || missing;
  const needsModels = !!health && !health.image?.ready && (health.image?.present ?? 0) < (health.image?.total ?? 0);

  const generate = async () => {
    if (reason) return;
    setSubmitting(true);
    try {
      if (newProject !== null) { await api.addProject(projectName); refreshProjects(); setProject(projectName); setNewProject(null); }
      const job = await api.createImage({
        prompt: fullPrompt, refs: filled.map(r => r.path), aspect: shape, project: projectName, seed: seedLocked ? seed : null,
      });
      save({ project: projectName, aspect: shape });
      if (!seedLocked) setSeed(job.seed);
      toast(ahead ? `Queued — ${ahead} ahead of it.` : "Making the image now.");
    } catch (e) {
      toast((e as Error).message, "error");
    } finally { setSubmitting(false); }
  };

  const animate = async (j: Job) => {
    try {
      const kf = await api.toKeyframe(j.id);
      setDraft({ upload: kf, prompt: "", project: j.project });
      go("create");
    } catch (e) { toast((e as Error).message, "error"); }
  };
  const useAsRef = (j: Job) => {
    if (!j.output_path || !j.video_url) return;
    const slot = refs.findIndex(r => r === null);
    if (slot === -1) { toast("All three reference slots are full — remove one first.", "info"); return; }
    const r: Ref = { path: j.output_path, url: j.video_url, width: j.width, height: j.height, orientation: orientationOf(j.width, j.height) };
    setRefs(list => list.map((x, i) => (i === slot ? r : x)));
  };

  return (
    <div className="mx-auto grid max-w-[1400px] grid-cols-1 gap-8 px-10 py-8 xl:grid-cols-[minmax(0,1.15fr)_minmax(420px,0.85fr)]">
      {/* References + results */}
      <div className="flex flex-col gap-6">
        {needsModels && (
          <div className="flex items-start justify-between gap-4 rounded-[3px] border border-warn/35 bg-warn/5 px-4 py-3 text-sm">
            <span className="flex items-start gap-2 text-warn"><AlertTriangle size={16} className="mt-0.5 shrink-0" />{health!.image.reason}</span>
            <button className="btn btn-secondary shrink-0 text-xs" onClick={() => go("models")}>Models</button>
          </div>
        )}

        <Section label="Cast · optional" right={filled.length > 0 && <button className="btn btn-ghost text-xs" onClick={() => setRefs([null, null, null])}><X size={14} />Clear all</button>}>
          <div className="grid grid-cols-3 gap-3">
            {refs.map((r, i) => (
              <div key={i}
                onDragOver={e => { e.preventDefault(); setDragSlot(i); }}
                onDragLeave={() => setDragSlot(null)}
                onDrop={e => { e.preventDefault(); setDragSlot(null); onFile(e.dataTransfer.files[0], i); }}
                onClick={() => { if (!r) { pickSlot.current = i; fileRef.current?.click(); } }}
                className={`relative flex aspect-[3/4] items-center justify-center overflow-hidden rounded-[3px] border-2 border-dashed transition-colors ${r ? "border-transparent bg-[#030820]" : dragSlot === i ? "cursor-copy border-accent bg-accent/5" : "cursor-pointer border-hairline bg-surface hover:border-accent/60"}`}>
                {r ? (
                  <>
                    <img src={r.url} alt={`Picture ${i + 1}`} className="h-full w-full object-cover" />
                    <span className="absolute top-2 left-2 rounded-[3px] bg-ground/85 px-2 py-0.5 font-mono text-[10px] tracking-wider text-ink-2">PICTURE {i + 1}</span>
                    <button className="btn btn-ghost absolute top-1.5 right-1.5 bg-ground/70 p-1" title="Remove"
                      onClick={e => { e.stopPropagation(); setRefs(list => list.map((x, j) => (j === i ? null : x))); }}><X size={14} /></button>
                  </>
                ) : (
                  <div className="flex flex-col items-center px-3 text-center">
                    <UserPlus size={24} className="mb-2 text-accent" />
                    <p className="display text-lg">{busySlot === i ? "Uploading…" : `Picture ${i + 1}`}</p>
                    <p className="mt-1 text-[11px] text-muted">drop · click · ⌘V</p>
                  </div>
                )}
              </div>
            ))}
          </div>
          <input ref={fileRef} type="file" accept="image/png,image/jpeg,image/webp" hidden
            onChange={e => { onFile(e.target.files?.[0], pickSlot.current); e.target.value = ""; }} />
          <p className="mt-2 text-[12px] leading-relaxed text-muted">
            Drop in character or location photos and name them in the prompt: <span className="text-ink-2">"The man in Picture 1 points a gun at the woman in Picture 2."</span> Leave them empty to make an image from the prompt alone.
          </p>
        </Section>

        {running && (
          <div className="card wf-grad-border p-4">
            <div className="mb-2 flex items-end justify-between">
              <span className="display text-xl">{running.live?.label ?? "Starting…"}</span>
              <span className="display wf-grad-text text-2xl">{Math.round(running.live?.percent ?? 0)}%</span>
            </div>
            <div className={`progress ${!running.live || running.live.stage === "load" ? "indeterminate" : ""}`}><div style={{ width: `${running.live?.percent ?? 0}%` }} /></div>
            <p className="mt-2 line-clamp-1 text-[12px] text-muted">{running.prompt}</p>
          </div>
        )}

        <Section label="Recent images" right={recent.length > 0 && <button className="text-[13px] text-accent hover:text-accent-hover" onClick={() => go("library")}>All in Library →</button>}>
          {recent.length === 0 ? (
            <div className="card px-5 py-6 text-sm text-muted">Finished images show up here. Animate one to send it to Create as a keyframe.</div>
          ) : (
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              {recent.map(j => (
                <div key={j.id} className="card group overflow-hidden">
                  <div className="relative aspect-video bg-[#02061a]">
                    {j.thumb_url && <img src={j.thumb_url} alt="" className="absolute inset-0 h-full w-full object-cover" />}
                    <div className="absolute inset-0 flex items-center justify-center gap-1.5 bg-ground/70 opacity-0 transition-opacity group-hover:opacity-100">
                      <button className="btn btn-primary px-2 py-1 text-[11px]" onClick={() => animate(j)} title="Send to Create as the keyframe"><Clapperboard size={13} />Animate</button>
                      <button className="btn btn-secondary px-2 py-1 text-[11px]" onClick={() => useAsRef(j)} title="Add as a reference picture"><Plus size={13} />Ref</button>
                    </div>
                  </div>
                  <p className="truncate px-2 py-1.5 font-mono text-[10px] text-muted">{timeAgo(j.finished_at)} · {fmtDuration(j.render_seconds)}</p>
                </div>
              ))}
            </div>
          )}
        </Section>
      </div>

      {/* Controls */}
      <div className="flex flex-col gap-6">
        <Section label="Describe the image">
          <textarea className="field min-h-[170px] resize-y text-[15px] leading-relaxed" value={prompt}
            placeholder={filled.length > 1
              ? "Who is where, doing what. e.g. The man in Picture 1 and the woman in Picture 2 stand face to face in a rain-soaked alley at night, neon light on wet brick, cinematic, 35mm film still."
              : "Describe the shot like a film still: subject, action, setting, light, lens. e.g. A spy in a dark suit raises a pistol in a rain-soaked alley at night, neon reflections on wet pavement, cinematic, 35mm."}
            onChange={e => setPrompt(e.target.value)} />
          <p className="mt-1.5 text-[12px] text-muted">Plain visual description works best — what's in the frame, not instructions.</p>
        </Section>

        <div className="-mt-2 flex flex-col gap-2">
          <PromptBuilder kind="image" picks={picks} onPicks={setPicks} onLibrary={setRecipe} />
          {Object.keys(picks).length > 0 && (
            <p className="rounded-[3px] border border-hairline bg-ground px-3 py-2 text-[12px] leading-relaxed text-ink-2">
              <span className="eyebrow mr-2">Qwen reads</span>{fullPrompt}
            </p>
          )}
        </div>

        <Section label="Shape">
          <div className="seg">
            {SHAPES.map(([k, label]) => {
              const [sw, sh] = ip.sizes[k];
              return (
                <button key={k} aria-pressed={shape === k} onClick={() => setAspect(k)}>
                  {label} <span className="ml-1 font-mono text-[11px] text-muted">{sw}×{sh}</span>
                </button>
              );
            })}
          </div>
          <p className="mt-1.5 text-[12px] text-muted">
            Landscape and portrait are 2× the Standard video size, so a still animates without stretching. The shape is the final frame's — reference photos can be any shape.
          </p>
        </Section>

        <Section label="Project">
          {newProject === null ? (
            <div className="flex gap-2">
              <select className="field" value={project} onChange={e => setProject(e.target.value)}>
                {projects.map(pr => <option key={pr.name} value={pr.name}>{pr.name}{pr.renders ? ` · ${pr.renders}` : ""}</option>)}
              </select>
              <button className="btn btn-secondary" onClick={() => setNewProject("")}><Plus size={16} />New</button>
            </div>
          ) : (
            <div className="flex gap-2">
              <input autoFocus className="field" placeholder="Project name, e.g. Farola Run" value={newProject}
                onChange={e => setNewProject(e.target.value)} maxLength={60} />
              <button className="btn btn-ghost" onClick={() => setNewProject(null)}>Cancel</button>
            </div>
          )}
        </Section>

        <Section label="Seed">
          <div className="flex items-center gap-2">
            <button className={`btn ${seedLocked ? "btn-secondary" : "btn-primary"}`} onClick={() => setSeedLocked(false)}><Dice5 size={16} />Random</button>
            <button className={`btn ${seedLocked ? "btn-primary" : "btn-secondary"}`} onClick={() => setSeedLocked(true)}>{seedLocked ? <Lock size={16} /> : <Unlock size={16} />}Lock</button>
            <input className="field font-mono" disabled={!seedLocked} value={seed} inputMode="numeric"
              onChange={e => setSeed(Math.max(0, Math.min(2 ** 32 - 1, Number(e.target.value.replace(/\D/g, "")) || 0)))} />
          </div>
          <p className="mt-1.5 text-[12px] text-muted">{seedLocked ? "Same seed + same prompt + same pictures = same image." : "A new seed every time. Lock it when you like a composition and want to tweak the words."}</p>
        </Section>

        <div className="flex flex-col gap-2 pt-1">
          <button className="btn btn-primary display h-16 text-[26px] tracking-wide" disabled={!!reason || submitting} onClick={generate}>
            <ImagePlus size={22} />{submitting ? "Queuing…" : "Make image"}
          </button>
          <div className="flex items-center justify-between text-[13px]">
            <span className={reason ? (blocked ? "text-bad" : "text-muted") : "text-ink-2"}>
              {reason || `${w}×${h} · ${filled.length ? `${filled.length} reference${filled.length > 1 ? "s" : ""}` : "text only"} · ${ip.avg_seconds ? `about ${fmtDuration(ip.avg_seconds)}` : "first image — no estimate yet"}${ahead ? ` · ${ahead} ahead in line` : ""}`}
            </span>
            {ahead > 0 && <button className="text-accent hover:text-accent-hover" onClick={() => go("renders")}>View queue →</button>}
          </div>
        </div>
      </div>
    </div>
  );
}

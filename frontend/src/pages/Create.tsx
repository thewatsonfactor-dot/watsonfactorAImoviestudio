import { AlertTriangle, ChevronDown, Dice5, ImagePlus, Lock, Plus, RefreshCw, Unlock, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, estimateTokens, fmtDuration, type Forecast, type Upload } from "../lib/api";
import { useStudio } from "../lib/store";
import { Section, StatCard } from "../components/ui";

const LS = "wfstudio.create";
function remember(): Record<string, string> {
  try { return JSON.parse(localStorage.getItem(LS) || "{}"); } catch { return {}; }
}
function save(v: Record<string, string>) {
  try { localStorage.setItem(LS, JSON.stringify({ ...remember(), ...v })); } catch { /* storage unavailable */ }
}

export default function Create() {
  const { health, presets, projects, refreshProjects, toast, go, draft, setDraft, queueIds, jobs } = useStudio();
  const mem = remember();
  const [upload, setUpload] = useState<Upload | null>(null);
  const [uploading, setUploading] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [prompt, setPrompt] = useState("");
  const [negative, setNegative] = useState<string | null>(null);
  const [project, setProject] = useState(mem.project || "");
  const [newProject, setNewProject] = useState<string | null>(null);
  const [preset, setPreset] = useState(mem.preset || "standard");
  const [length, setLength] = useState(mem.length || "standard");
  const [seedLocked, setSeedLocked] = useState(false);
  const [seed, setSeed] = useState<number>(() => Math.floor(Math.random() * 2 ** 32));
  const [advanced, setAdvanced] = useState(false);
  const [dims, setDims] = useState<{ w: string; h: string }>({ w: "", h: "" });
  const [fc, setFc] = useState<Forecast | null>(null);
  const [tryAnyway, setTryAnyway] = useState(false);
  const [steps, setSteps] = useState<string>("");
  const [submitting, setSubmitting] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  // Remix from the Library pre-fills everything.
  useEffect(() => {
    if (!draft) return;
    if (draft.upload) setUpload({ ...draft.upload });
    if (draft.prompt != null) setPrompt(draft.prompt);
    if (draft.negative != null) setNegative(draft.negative);
    if (draft.project) setProject(draft.project);
    if (draft.preset) setPreset(draft.preset);
    if (draft.length) setLength(draft.length);
    if (draft.seed != null) { setSeed(draft.seed); setSeedLocked(true); }
    setDraft(null);
  }, [draft, setDraft]);

  // First visit: fall back to the defaults from Settings.
  useEffect(() => {
    if (mem.project && mem.preset && mem.length) return;
    api.settings().then(({ settings: s }) => {
      if (!mem.project) setProject(p => p || String(s.default_project));
      if (!mem.preset) setPreset(String(s.default_preset));
      if (!mem.length) setLength(String(s.default_length));
    }).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onFile = useCallback(async (file: File | undefined | null) => {
    if (!file) return;
    if (!/^image\/(png|jpe?g|webp)$/.test(file.type)) { toast("Use a PNG, JPG or WEBP keyframe.", "error"); return; }
    setUploading(true);
    try { setUpload(await api.upload(file)); }
    catch (e) { toast((e as Error).message, "error"); }
    finally { setUploading(false); }
  }, [toast]);

  useEffect(() => {
    const onPaste = (e: ClipboardEvent) => {
      const item = [...(e.clipboardData?.items || [])].find(i => i.type.startsWith("image/"));
      if (item) onFile(item.getAsFile());
    };
    window.addEventListener("paste", onPaste);
    return () => window.removeEventListener("paste", onPaste);
  }, [onFile]);

  // Memory forecast for the exact size that will be rendered.
  const fcPreset = presets?.presets[preset];
  const [fw, fh] = fcPreset ? presets!.tiers[fcPreset.tier][upload?.orientation || "landscape"] : [0, 0];
  const fW = advanced && +dims.w ? +dims.w : fw, fH = advanced && +dims.h ? +dims.h : fh;
  const fFrames = presets?.lengths[length]?.frames ?? 0;
  useEffect(() => {
    if (!fW || !fH || !fFrames) return;
    let live = true;
    setTryAnyway(false);
    api.forecast(fW, fH, fFrames).then(r => { if (live) setFc(r); }).catch(() => { if (live) setFc(null); });
    return () => { live = false; };
  }, [fW, fH, fFrames]);

  if (!presets) return <div className="p-10 text-muted">Loading…</div>;

  const tokens = estimateTokens(prompt);
  const tokenLevel = tokens > presets.token_limit ? "bad" : tokens >= presets.token_warn ? "warn" : "ok";
  const p = presets.presets[preset];
  const orientation = upload?.orientation || "landscape";
  const [tw, th] = presets.tiers[p.tier][orientation];
  const avg = p.avg_seconds?.[length];
  const ahead = queueIds.length + Object.values(jobs).filter(j => j.status === "running").length;
  const projectName = newProject !== null ? newProject.trim() : project;

  const blocked = !health ? "Can't reach the Studio backend." : health.blocked_reason;
  const missing = !upload ? "Drop a keyframe first." : !prompt.trim() ? "Write a motion prompt." :
    !projectName ? "Pick a project." : null;
  const tooBig = fc?.level === "failed" && !tryAnyway ? "This size ran out of memory here before." : null;
  const reason = blocked || missing || tooBig;

  const generate = async () => {
    if (reason) return;
    setSubmitting(true);
    try {
      if (newProject !== null) { await api.addProject(projectName); refreshProjects(); setProject(projectName); setNewProject(null); }
      const body: Record<string, unknown> = {
        input_path: upload!.path, prompt, project: projectName, preset, length,
        seed: seedLocked ? seed : null,
      };
      if (fc?.level === "failed" && tryAnyway) body.allow_risky = true;
      if (negative !== null) body.negative = negative;
      if (advanced && dims.w && dims.h) { body.width = +dims.w; body.height = +dims.h; }
      if (advanced && steps) body.steps = +steps;
      const job = await api.createJob(body);
      save({ project: projectName, preset, length });
      if (!seedLocked) setSeed(job.seed);
      toast(ahead ? `Queued — ${ahead} ahead of it.` : "Rendering now. Follow it in Renders.");
    } catch (e) {
      toast((e as Error).message, "error");
    } finally { setSubmitting(false); }
  };

  const memoryWarn = health && health.pills.memory.level !== "green";

  return (
    <div className="mx-auto grid max-w-[1400px] grid-cols-1 gap-8 px-10 py-8 xl:grid-cols-[minmax(0,1.15fr)_minmax(420px,0.85fr)]">
      {/* Keyframe */}
      <div className="flex flex-col gap-6">
        <Section label="Keyframe" right={upload && <button className="btn btn-ghost text-xs" onClick={() => setUpload(null)}><X size={14} />Clear</button>}>
          <div
            onDragOver={e => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            onDrop={e => { e.preventDefault(); setDragOver(false); onFile(e.dataTransfer.files[0]); }}
            onClick={() => !upload && fileRef.current?.click()}
            className={`relative flex aspect-video items-center justify-center overflow-hidden rounded-[3px] border-2 border-dashed transition-colors ${upload ? "border-transparent bg-[#030820]" : dragOver ? "cursor-copy border-accent bg-accent/5" : "cursor-pointer border-hairline bg-surface hover:border-accent/60"}`}>
            {upload ? (
              <>
                <img src={upload.url} alt="Keyframe" className="h-full w-full object-contain" />
                <div className="absolute bottom-3 left-3 flex gap-2">
                  <span className="rounded-[3px] bg-ground/85 px-2.5 py-1 font-mono text-[11px] tracking-wider text-ink-2 uppercase">{upload.orientation}</span>
                  <span className="rounded-[3px] bg-ground/85 px-2.5 py-1 font-mono text-[11px] tracking-wider text-ink-2">{upload.width}×{upload.height} → {tw}×{th}</span>
                </div>
                <button className="btn btn-secondary absolute right-3 bottom-3 text-xs" onClick={e => { e.stopPropagation(); fileRef.current?.click(); }}>
                  <RefreshCw size={14} />Swap
                </button>
              </>
            ) : (
              <div className="flex flex-col items-center text-center">
                <div className="wf-grad-border mb-5 rounded-full p-4"><ImagePlus size={30} className="text-accent" /></div>
                <p className="display text-3xl">{uploading ? "Uploading…" : "Drop your keyframe"}</p>
                <p className="mt-2 text-sm text-muted">PNG, JPG or WEBP · click to browse · or paste with ⌘V</p>
              </div>
            )}
            <input ref={fileRef} type="file" accept="image/png,image/jpeg,image/webp" hidden onChange={e => { onFile(e.target.files?.[0]); e.target.value = ""; }} />
          </div>
        </Section>

        <div className="grid grid-cols-3 gap-4">
          <StatCard value={health?.stats.renders_today ?? "—"} caption="renders today" />
          <StatCard value={fmtDuration(health?.stats.avg_render_seconds)} caption="average render time" hint="Last 10 finished renders" />
          <StatCard value={health?.disk.ssd ? `${Math.round(health.disk.ssd.free_gb)} GB` : "—"} caption="free on the SSD" />
        </div>
      </div>

      {/* Controls */}
      <div className="flex flex-col gap-6">
        <Section label="Motion prompt" right={
          <span className={`font-mono text-[11px] ${tokenLevel === "bad" ? "text-bad" : tokenLevel === "warn" ? "text-warn" : "text-muted"}`}>
            ≈ {tokens} / {presets.token_limit} tokens
          </span>}>
          <textarea className="field min-h-[150px] resize-y text-[15px] leading-relaxed" value={prompt}
            placeholder="What moves, and how the camera moves. e.g. She turns her head toward the window, hair lifting in the breeze; slow push in, handheld."
            onChange={e => setPrompt(e.target.value)} />
          <div className="progress mt-2"><div style={{ width: `${Math.min(100, tokens / presets.token_limit * 100)}%`, background: tokenLevel === "bad" ? "var(--color-bad)" : tokenLevel === "warn" ? "var(--color-warn)" : undefined }} /></div>
          {tokenLevel !== "ok" && (
            <p className={`mt-2 flex items-start gap-2 text-[13px] ${tokenLevel === "bad" ? "text-bad" : "text-warn"}`}>
              <AlertTriangle size={14} className="mt-0.5 shrink-0" />
              {tokenLevel === "bad" ? "Wan ignores everything past here — trim it." : "Getting long. Wan only reads about 512 tokens; keep it to motion and camera."}
            </p>
          )}
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

        <Section label="Length">
          <div className="seg">
            {Object.entries(presets.lengths).map(([k, l]) => (
              <button key={k} aria-pressed={length === k} onClick={() => setLength(k)}>
                {l.label} <span className="ml-1 font-mono text-[11px] text-muted">{l.approx}</span>
              </button>
            ))}
          </div>
        </Section>

        <Section label="Quality">
          <div className="grid grid-cols-3 gap-2.5">
            {Object.entries(presets.presets).map(([k, d]) => {
              const on = preset === k;
              const [w, h] = presets.tiers[d.tier][orientation];
              return (
                <button key={k} onClick={() => setPreset(k)}
                  className={`rounded-[3px] p-3.5 text-left transition-colors ${on ? "wf-grad-border" : "border border-hairline bg-ground hover:border-accent/50"}`}>
                  <div className="flex items-center justify-between">
                    <span className="display text-xl">{d.label}</span>
                    {d.experimental && <span className="rounded-[3px] bg-warn/15 px-1.5 py-0.5 font-mono text-[9px] tracking-wider text-warn">EXPERIMENTAL</span>}
                  </div>
                  <div className="mt-1 font-mono text-[11px] text-ink-2">{w}×{h} · {d.steps} steps</div>
                  <div className="mt-1.5 text-[12px] leading-snug text-muted">{d.note}</div>
                </button>
              );
            })}
          </div>
        </Section>

        <Section label="Seed">
          <div className="flex items-center gap-2">
            <button className={`btn ${seedLocked ? "btn-secondary" : "btn-primary"}`} onClick={() => setSeedLocked(false)}><Dice5 size={16} />Random</button>
            <button className={`btn ${seedLocked ? "btn-primary" : "btn-secondary"}`} onClick={() => setSeedLocked(true)}>{seedLocked ? <Lock size={16} /> : <Unlock size={16} />}Lock</button>
            <input className="field font-mono" disabled={!seedLocked} value={seed} inputMode="numeric"
              onChange={e => setSeed(Math.max(0, Math.min(2 ** 32 - 1, Number(e.target.value.replace(/\D/g, "")) || 0)))} />
          </div>
          <p className="mt-1.5 text-[12px] text-muted">{seedLocked ? "Same seed + same settings = same shot. Change one thing at a time." : "A new seed every render. Lock it when you find a take you like."}</p>
        </Section>

        <div>
          <button className="flex items-center gap-2 text-sm text-ink-2 hover:text-ink" onClick={() => setAdvanced(a => !a)}>
            <ChevronDown size={16} className={`transition-transform ${advanced ? "" : "-rotate-90"}`} />Advanced
          </button>
          {advanced && (
            <div className="card mt-3 flex flex-col gap-4 p-4">
              <div>
                <label className="eyebrow mb-1.5 block">Negative prompt</label>
                <textarea className="field min-h-[70px] text-sm" value={negative ?? presets.negative_default} onChange={e => setNegative(e.target.value)} />
                <p className="mt-1 text-[12px] text-muted">Has little effect at the 4-step speed settings (CFG 1), which every preset uses.</p>
              </div>
              <div className="grid grid-cols-3 gap-3">
                <div>
                  <label className="eyebrow mb-1.5 block">Width</label>
                  <input className="field font-mono" placeholder={String(tw)} value={dims.w} onChange={e => setDims(d => ({ ...d, w: e.target.value.replace(/\D/g, "") }))} />
                </div>
                <div>
                  <label className="eyebrow mb-1.5 block">Height</label>
                  <input className="field font-mono" placeholder={String(th)} value={dims.h} onChange={e => setDims(d => ({ ...d, h: e.target.value.replace(/\D/g, "") }))} />
                </div>
                <div>
                  <label className="eyebrow mb-1.5 block">Steps</label>
                  <input className="field font-mono" placeholder={String(p.steps)} value={steps} onChange={e => setSteps(e.target.value.replace(/\D/g, ""))} />
                </div>
              </div>
              <p className="text-[12px] text-muted">Width and height snap to multiples of 16. Leave blank to use the preset.</p>
            </div>
          )}
        </div>

        {memoryWarn && (
          <div className="flex items-start gap-2 rounded-[3px] border border-warn/30 bg-warn/5 px-4 py-3 text-sm text-warn">
            <AlertTriangle size={16} className="mt-0.5 shrink-0" />Close Chrome tabs and other apps before rendering — memory is tight.
          </div>
        )}

        {fc && fc.level !== "ok" && (
          <div className={`flex flex-col gap-2 rounded-[3px] border px-4 py-3 text-sm ${fc.level === "failed" ? "border-bad/40 bg-bad/5 text-bad" : "border-warn/30 bg-warn/5 text-warn"}`}>
            <div className="flex items-start gap-2"><AlertTriangle size={16} className="mt-0.5 shrink-0" />{fc.message}</div>
            {fc.level === "failed" && (
              <label className="flex items-center gap-2 pl-6 text-[13px] text-ink-2">
                <input type="checkbox" checked={tryAnyway} onChange={e => setTryAnyway(e.target.checked)} />
                Try anyway (it will most likely fail)
              </label>
            )}
          </div>
        )}

        <div className="flex flex-col gap-2 pt-1">
          <button className="btn btn-primary display h-16 text-[26px] tracking-wide" disabled={!!reason || submitting} onClick={generate}>
            {submitting ? "Queuing…" : "Generate"}
          </button>
          <div className="flex items-center justify-between text-[13px]">
            <span className={reason ? (blocked ? "text-bad" : "text-muted") : "text-ink-2"}>
              {reason || (avg ? `About ${fmtDuration(avg)} on this Mac${ahead ? ` · ${ahead} ahead in line` : ""}` : "First run at this setting — no estimate yet")}
            </span>
            {ahead > 0 && <button className="text-accent hover:text-accent-hover" onClick={() => go("renders")}>View renders →</button>}
          </div>
        </div>
      </div>
    </div>
  );
}

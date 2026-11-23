import { Aperture, ChevronDown, Copy, Lightbulb, Wand2, Wrench } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { api, fillTemplate, LOCK_DEFAULTS, lockText, type Lens, type LensLocks, type LensStage } from "../lib/api";
import { useStudio } from "../lib/store";

/** LENS: the anamorphic blockbuster look. Stage templates fill the prompt box; the project's look
 *  locks (realism, lens, lighting, shadow side) are appended to every prompt the engine reads, so the
 *  look holds shot to shot. Locks save per project. The parent composes the final prompt with the
 *  `suffix` this panel reports through onLocks. */
export function LensPanel({ kind, project, onFill, onAppend, onLocks, onAspect, onFinish }: {
  kind: "image" | "video";
  project: string;
  onFill: (text: string) => void;
  onAppend: (text: string) => void;
  onLocks: (suffix: string) => void;
  onAspect?: (aspect: string) => void;
  onFinish?: (finish: string) => void;
}) {
  const { toast } = useStudio();
  const [lens, setLens] = useState<Lens | null>(null);
  const [open, setOpen] = useState(true);
  const [stageId, setStageId] = useState<string>("");
  const [values, setValues] = useState<Record<string, string>>({});
  const [locks, setLocks] = useState<LensLocks>({});
  const [fixId, setFixId] = useState("");
  const [editLens, setEditLens] = useState(false);
  const saveTimer = useRef<number | null>(null);

  useEffect(() => { api.lens().then(setLens).catch(() => {}); }, []);

  // Each project keeps its own locks; switching project loads that project's.
  useEffect(() => {
    if (!lens) return;
    setLocks(lens.projects[project] ?? {});
  }, [lens, project]);

  const stages = useMemo(() => (lens?.stages ?? []).filter(s => s.kind === kind), [lens, kind]);
  const stage: LensStage | null = stages.find(s => s.id === stageId) ?? null;
  const l = { ...LOCK_DEFAULTS, ...locks };
  const suffix = lockText(lens, locks, kind, stage && !stage.copy_only ? stage : null);

  useEffect(() => { onLocks(suffix); }, [suffix, onLocks]);
  useEffect(() => { if (onFinish) onFinish(locks.finish ?? ""); }, [locks.finish, onFinish]);

  if (!lens) return null;

  const update = (patch: LensLocks) => {
    const next = { ...locks, ...patch };
    setLocks(next);
    if (!project) return;
    if (saveTimer.current) window.clearTimeout(saveTimer.current);
    saveTimer.current = window.setTimeout(() => {
      api.saveLens(project, next).then(setLens).catch(e => toast((e as Error).message, "error"));
    }, 500);
  };

  const pickStage = (id: string) => {
    setStageId(id);
    setValues({});
    const s = stages.find(x => x.id === id);
    if (s?.aspect && onAspect) onAspect(s.aspect);
  };

  const filled = stage ? fillTemplate(stage, values) : "";
  const copyForSeedance = () => {
    if (!stage) return;
    const text = [filled, lockText(lens, locks, "video", stage)].filter(Boolean).join(" ");
    navigator.clipboard.writeText(text).then(() => toast("Seedance prompt copied — paste it in Higgsfield with the plates attached in order."));
  };
  const fix = lens.fixes.find(f => f.id === fixId);
  const onCount = [l.realism_on, l.lens_on, l.lighting_on && !!(locks.lighting_text || "").trim(), l.shadow_on].filter(Boolean).length;

  const Toggle = ({ on, label, help, onChange }: { on: boolean; label: string; help?: string; onChange: (v: boolean) => void }) => (
    <label className="flex cursor-pointer items-start gap-2.5 py-1" title={help}>
      <input type="checkbox" className="mt-1 accent-[var(--color-accent)]" checked={on} onChange={e => onChange(e.target.checked)} />
      <span>
        <span className="text-[13px] text-ink">{label}</span>
        {help && <span className="block text-[11px] leading-snug text-muted">{help}</span>}
      </span>
    </label>
  );

  return (
    <div className="card wf-grad-border p-4">
      <button className="flex w-full items-center justify-between text-left" onClick={() => setOpen(o => !o)}>
        <span className="eyebrow flex items-center gap-1.5"><Aperture size={13} />LENS · film look{project ? ` · ${project}` : ""}{onCount ? ` · ${onCount} lock${onCount > 1 ? "s" : ""} on` : ""}</span>
        <ChevronDown size={15} className={`text-muted transition-transform ${open ? "" : "-rotate-90"}`} />
      </button>

      {open && (
        <div className="mt-3 flex flex-col gap-4">
          {/* Stage template */}
          <div>
            <label className="mb-1 block text-[12px] text-muted">{kind === "image" ? "What are you making?" : "Prompt template"}</label>
            <div className="relative">
              <select className="field appearance-none pr-8 text-sm" value={stageId} onChange={e => pickStage(e.target.value)}>
                <option value="">Free prompt (locks still apply)</option>
                {stages.map(s => <option key={s.id} value={s.id}>{s.label}</option>)}
              </select>
              <ChevronDown size={14} className="pointer-events-none absolute top-1/2 right-3 -translate-y-1/2 text-muted" />
            </div>
          </div>

          {stage && (
            <div className="flex flex-col gap-3 rounded-[3px] border border-hairline bg-ground p-3">
              <ul className="flex flex-col gap-1">
                {stage.tips.map(t => <li key={t} className="flex gap-1.5 text-[12px] leading-snug text-ink-2"><Lightbulb size={12} className="mt-0.5 shrink-0 text-accent" />{t}</li>)}
              </ul>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                {stage.fields.map(f => (
                  <div key={f.id} className={f.options ? "" : "sm:col-span-2"}>
                    <label className="mb-1 block text-[11px] text-muted">{f.label}</label>
                    {f.options ? (
                      <select className="field text-sm" value={values[f.id] ?? f.default} onChange={e => setValues(v => ({ ...v, [f.id]: e.target.value }))}>
                        {f.options.map(o => <option key={o} value={o}>{f.id === "focal" ? `${o}mm` : f.id === "distance" ? `${o} m` : o}</option>)}
                      </select>
                    ) : (
                      <input className="field text-sm" placeholder={f.placeholder} value={values[f.id] ?? ""} onChange={e => setValues(v => ({ ...v, [f.id]: e.target.value }))} />
                    )}
                  </div>
                ))}
              </div>
              {stage.id === "location" && (values.focal ?? "35") === "24" && (
                <p className="text-[12px] text-warn">24mm is for places. Never put a face on 24mm; faces get portrait framing.</p>
              )}
              <div className="flex justify-end gap-2">
                {stage.copy_only ? (
                  <button className="btn btn-primary text-xs" onClick={copyForSeedance}><Copy size={13} />Copy for Higgsfield</button>
                ) : (
                  <button className="btn btn-primary text-xs" onClick={() => { onFill(filled); toast("Template filled in — edit it above."); }}><Wand2 size={13} />Fill the prompt</button>
                )}
              </div>
            </div>
          )}

          {/* Look locks */}
          <div>
            <div className="eyebrow mb-1">Look locks · saved to this project</div>
            <Toggle on={l.realism_on} label="Realism (no plastic skin, no CGI)" help={lens.lock_help.realism} onChange={v => update({ realism_on: v })} />
            <Toggle on={l.lens_on} label="Lens lock (anamorphic profile)" help={lens.lock_help.lens} onChange={v => update({ lens_on: v })} />
            {l.lens_on && (
              <div className="mb-1 ml-6">
                {editLens ? (
                  <textarea className="field min-h-[70px] text-[12px]" value={locks.lens_text ?? lens.locks.lens} onChange={e => update({ lens_text: e.target.value })} />
                ) : (
                  <p className="text-[11px] leading-snug text-ink-2">{(locks.lens_text || "").trim() || lens.locks.lens} <button className="text-accent" onClick={() => setEditLens(true)}>Edit</button></p>
                )}
              </div>
            )}
            <Toggle on={l.lighting_on} label="Lighting lock (this location's light)" help={lens.lock_help.lighting} onChange={v => update({ lighting_on: v })} />
            {l.lighting_on && (
              <div className="mb-1 ml-6">
                <textarea className="field min-h-[80px] text-[12px]" placeholder={lens.locks.lighting_example}
                  value={locks.lighting_text ?? ""} onChange={e => update({ lighting_text: e.target.value })} />
                {!(locks.lighting_text || "").trim() && <p className="mt-1 text-[11px] text-warn">Empty, so nothing is added yet. Describe what your lighting plates share and end with a NEVER line.</p>}
              </div>
            )}
            <Toggle on={l.shadow_on} label="Shadow side" help={lens.lock_help.shadow_side} onChange={v => update({ shadow_on: v })} />
            {kind === "video" && onFinish && (
              <Toggle on={locks.finish === "film"} label="Film grain finish"
                help="Adds organic 35mm grain to the finished clip, after the render passes its checks. The clean original is kept in .raw/."
                onChange={v => update({ finish: v ? "film" : "" })} />
            )}
            {stage && !stage.copy_only && stage.locks.length < 4 && (
              <p className="mt-1 text-[11px] text-muted">{stage.label.replace(/^\d · /, "")} uses only: {stage.locks.join(", ").replace("shadow_side", "shadow side")}.</p>
            )}
          </div>

          {/* Failure fixes */}
          <div>
            <label className="mb-1 flex items-center gap-1.5 text-[12px] text-muted"><Wrench size={12} />Something look wrong?</label>
            <div className="relative">
              <select className="field appearance-none pr-8 text-sm" value={fixId} onChange={e => setFixId(e.target.value)}>
                <option value="">Pick what's wrong…</option>
                {lens.fixes.map(f => <option key={f.id} value={f.id}>{f.problem}</option>)}
              </select>
              <ChevronDown size={14} className="pointer-events-none absolute top-1/2 right-3 -translate-y-1/2 text-muted" />
            </div>
            {fix && (
              <div className="mt-2 rounded-[3px] border border-hairline bg-ground px-3 py-2">
                <p className="text-[12px] leading-relaxed text-ink-2">{fix.fix}</p>
                {fix.add && (
                  <button className="btn btn-ghost mt-1 px-2 py-0.5 text-[11px]" onClick={() => { onAppend(fix.add); toast("Added to the prompt."); }}>
                    <Wand2 size={12} />Add "{fix.add.length > 48 ? `${fix.add.slice(0, 48)}…` : fix.add}"
                  </button>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

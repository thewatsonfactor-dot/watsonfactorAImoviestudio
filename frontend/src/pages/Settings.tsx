import { Power, RefreshCw, Save } from "lucide-react";
import { useEffect, useState } from "react";
import { api, type Settings as S } from "../lib/api";
import { useStudio } from "../lib/store";
import { Section } from "../components/ui";

const FIELDS: { key: string; label: string; hint: string }[] = [
  { key: "ssd_root", label: "SSD", hint: "Where the external drive mounts. Default /Volumes/WFStudio." },
  { key: "ssd_image", label: "SSD disk image (optional)", hint: "If the SSD is a disk image, its path. The Studio mounts it for you and detaches it on Stop." },
  { key: "engine_flags", label: "Engine flags (optional)", hint: "Extra ComfyUI flags, e.g. --disable-smart-memory. Restart the engine to apply." },
  { key: "models_dir", label: "Models folder", hint: "{ssd_root} is replaced with the SSD path." },
  { key: "output_dir", label: "Output folder", hint: "Every render lands here, one folder per project." },
  { key: "inputs_dir", label: "Keyframes folder", hint: "Uploaded keyframes are copied here." },
  { key: "comfy_url", label: "Engine address", hint: "ComfyUI. Leave at http://127.0.0.1:8188." },
  { key: "comfy_dir", label: "Engine install", hint: "Where ComfyUI lives. Default ~/ComfyUI." },
  { key: "min_free_gb", label: "Minimum free space (GB)", hint: "Renders are blocked below this much free space on the SSD." },
];

export default function Settings() {
  const { health, presets, projects, toast, refreshHealth } = useStudio();
  const [form, setForm] = useState<S | null>(null);
  const [raw, setRaw] = useState<S | null>(null);

  useEffect(() => { api.settings().then(r => { setForm(r.settings); setRaw(r.settings); }).catch(e => toast(e.message, "error")); }, [toast]);
  if (!form) return <div className="p-10 text-muted">Loading…</div>;
  const dirty = JSON.stringify(form) !== JSON.stringify(raw);

  const saveAll = async () => {
    try {
      const r = await api.saveSettings({ ...form, min_free_gb: Number(form.min_free_gb) });
      setForm(r.settings); setRaw(r.settings); refreshHealth(); toast("Settings saved.");
    } catch (e) { toast((e as Error).message, "error"); }
  };
  const engine = async (a: "start" | "restart" | "stop") => {
    try { await api.engine(a); toast(a === "stop" ? "Stopping the engine…" : `${a === "start" ? "Starting" : "Restarting"} the engine — about 20 seconds.`, "info"); setTimeout(refreshHealth, 3000); }
    catch (e) { toast((e as Error).message, "error"); }
  };

  const freeNow = async () => {
    try {
      const r = await api.freeMemory();
      toast(r.swap_released_mb == null ? "Asked the engine to free memory." : `Freed memory. Swap down ${Math.round(r.swap_released_mb)} MB.`, "info");
      refreshHealth();
    } catch (e) { toast((e as Error).message, "error"); }
  };

  return (
    <div className="mx-auto grid max-w-[1200px] grid-cols-1 gap-8 px-10 py-8 lg:grid-cols-[minmax(0,1fr)_360px]">
      <div className="flex flex-col gap-8">
        <Section label="Paths" right={<button className="btn btn-primary text-xs" disabled={!dirty} onClick={saveAll}><Save size={14} />Save</button>}>
          <div className="card flex flex-col gap-5 p-5">
            {FIELDS.map(f => (
              <div key={f.key}>
                <label className="mb-1.5 block text-sm text-ink-2">{f.label}</label>
                <input className="field font-mono text-[13px]" value={String(form[f.key] ?? "")} onChange={e => setForm({ ...form, [f.key]: e.target.value })} />
                <p className="mt-1 text-[12px] text-muted">{f.hint}</p>
              </div>
            ))}
          </div>
        </Section>

        <Section label="Defaults">
          <div className="card grid grid-cols-1 gap-5 p-5 md:grid-cols-3">
            <div>
              <label className="mb-1.5 block text-sm text-ink-2">Project</label>
              <select className="field" value={String(form.default_project)} onChange={e => setForm({ ...form, default_project: e.target.value })}>
                {projects.map(p => <option key={p.name}>{p.name}</option>)}
              </select>
            </div>
            <div>
              <label className="mb-1.5 block text-sm text-ink-2">Quality</label>
              <select className="field" value={String(form.default_preset)} onChange={e => setForm({ ...form, default_preset: e.target.value })}>
                {presets && Object.entries(presets.presets).map(([k, d]) => <option key={k} value={k}>{d.label}</option>)}
              </select>
            </div>
            <div>
              <label className="mb-1.5 block text-sm text-ink-2">Length</label>
              <select className="field" value={String(form.default_length)} onChange={e => setForm({ ...form, default_length: e.target.value })}>
                {presets && Object.entries(presets.lengths).map(([k, d]) => <option key={k} value={k}>{d.label} ({d.approx})</option>)}
              </select>
            </div>
          </div>
        </Section>
      </div>

      <div className="flex flex-col gap-8">
        <Section label="Engine">
          <div className="card flex flex-col gap-3 p-5">
            <p className="text-sm text-ink-2">{health?.pills.engine.reason ?? "Checking…"}</p>
            <div className="flex gap-2">
              {health?.engine.up
                ? <button className="btn btn-secondary flex-1" onClick={() => engine("restart")}><RefreshCw size={15} />Restart engine</button>
                : <button className="btn btn-primary flex-1" onClick={() => engine("start")}><Power size={15} />Start engine</button>}
              {health?.engine.up && <button className="btn btn-ghost" onClick={() => engine("stop")}>Stop</button>}
            </div>
            <button className="btn btn-secondary" disabled={!health?.engine.up} onClick={freeNow}><RefreshCw size={15} />Free memory now</button>
            <p className="text-[12px] text-muted">Unloads the models and releases cached memory. Handy when the Mac feels sluggish. The next render reloads the models (about a minute).</p>
            <p className="text-[12px] text-muted">Restart clears memory if renders start failing. A render in progress is lost.</p>
          </div>
        </Section>

        <Section label="This Mac">
          <dl className="card grid grid-cols-[110px_1fr] gap-y-2.5 p-5 font-mono text-[12px]">
            {[["Chip", health?.system.chip], ["Memory", health ? `${health.system.memory_gb} GB` : ""], ["macOS", health?.system.os],
              ["Engine", health?.engine.comfyui_version ?? "not running"], ["PyTorch", health?.engine.pytorch_version ?? "—"],
              ["GPU", health?.engine.device === "mps" ? "Metal (MPS) ✓" : health?.engine.device ?? "—"]].map(([k, v]) => (
              <div key={k} className="contents"><dt className="text-muted">{k}</dt><dd className="text-ink-2">{v}</dd></div>
            ))}
          </dl>
        </Section>

        <Section label="Library">
          <div className="card flex flex-col gap-3 p-5">
            <p className="text-sm text-ink-2">Every render has a settings file next to it. Rescan rebuilds the Library from those files.</p>
            <button className="btn btn-secondary" onClick={() => api.rescan().then(r => toast(r.added ? `Recovered ${r.added} renders.` : "Library is already up to date.")).catch(e => toast(e.message, "error"))}>
              <RefreshCw size={15} />Rescan the SSD
            </button>
          </div>
        </Section>
      </div>
    </div>
  );
}

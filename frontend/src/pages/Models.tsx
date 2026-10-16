import { AlertTriangle, CheckCircle2, Download, Loader2, XCircle } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api, fmtGB, type ModelItem, type ModelsStatus } from "../lib/api";
import { useStudio } from "../lib/store";
import { Confirm, Section, StatCard } from "../components/ui";

export default function Models() {
  const { health, toast } = useStudio();
  const [status, setStatus] = useState<ModelsStatus | null>(null);
  const [confirm, setConfirm] = useState<ModelItem | null>(null);

  const load = useCallback(() => api.models().then(setStatus).catch(e => toast(e.message, "error")), [toast]);
  useEffect(() => { load(); }, [load]);
  const downloading = status?.models.some(m => m.download && ["queued", "downloading"].includes(m.download.state));
  useEffect(() => {
    if (!downloading) return;
    const t = setInterval(load, 1500);
    return () => clearInterval(t);
  }, [downloading, load]);

  const ssdMounted = !health || !health.pills.ssd.reason.startsWith("SSD not connected");
  const onDiskGB = status ? status.models.reduce((a, m) => a + (m.state === "present" ? m.size_on_disk : 0), 0) : 0;

  return (
    <div className="mx-auto flex max-w-[1100px] flex-col gap-8 px-10 py-8">
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <StatCard value={status ? `${status.present}/${status.total}` : "—"} caption="model files ready" />
        <StatCard value={fmtGB(onDiskGB)} caption="models on the SSD" />
        <StatCard value={health?.disk.ssd ? `${Math.round(health.disk.ssd.free_gb)} GB` : "—"} caption="free on the SSD" />
        <StatCard value={health?.disk.internal ? `${Math.round(health.disk.internal.free_gb)} GB` : "—"} caption="free on the Mac" />
      </div>

      {!ssdMounted && (
        <div className="rounded-[3px] border border-bad/40 bg-bad/10 px-4 py-3 text-sm">{health?.pills.ssd.reason}</div>
      )}

      {health && health.workflow_problems.length > 0 && (
        <Section label="Engine check">
          <div className="card flex flex-col gap-2 border-warn/40 p-4">
            {health.workflow_problems.map(p => (
              <p key={p} className="flex items-start gap-2 text-sm text-warn"><AlertTriangle size={15} className="mt-0.5 shrink-0" />{p}</p>
            ))}
          </div>
        </Section>
      )}

      <Section label="Manifest" right={status && status.missing_gb > 0 ? <span className="font-mono text-[11px] text-warn">{status.missing_gb} GB still to download</span> : null}>
        <div className="card divide-y divide-hairline">
          {status?.models.map(m => {
            const dl = m.download;
            const active = dl && ["queued", "downloading"].includes(dl.state);
            const pct = dl && dl.total ? Math.min(100, (dl.bytes / dl.total) * 100) : 0;
            return (
              <div key={m.id} className="flex flex-col gap-2 px-5 py-4">
                <div className="flex items-center gap-4">
                  {m.state === "present" ? <CheckCircle2 size={20} className="shrink-0 text-ok" />
                    : active ? <Loader2 size={20} className="shrink-0 animate-spin text-accent" />
                    : <XCircle size={20} className="shrink-0 text-bad" />}
                  <div className="min-w-0 flex-1">
                    <p className="text-[15px]">{m.label}</p>
                    <p className="truncate font-mono text-[11px] text-muted">{m.folder}/{m.filename}</p>
                  </div>
                  <span className="font-mono text-[12px] text-ink-2">{fmtGB(m.size_bytes)}</span>
                  {m.state !== "present" && !active && (
                    <button className="btn btn-secondary text-xs" disabled={!ssdMounted} onClick={() => setConfirm(m)}><Download size={14} />Download</button>
                  )}
                </div>
                {m.state === "wrong_size" && !active && <p className="pl-9 text-[12px] text-warn">File is the wrong size ({fmtGB(m.size_on_disk)}) — probably a half-finished download. Download it again.</p>}
                {active && (
                  <div className="pl-9">
                    <div className="progress"><div style={{ width: `${pct}%` }} /></div>
                    <p className="mt-1 font-mono text-[11px] text-muted">{dl!.state === "queued" ? "Waiting for the download ahead of it…" : `${fmtGB(dl!.bytes)} of ${fmtGB(dl!.total)}`}</p>
                  </div>
                )}
                {dl?.state === "failed" && <p className="pl-9 text-[12px] text-bad">Download failed: {dl.error}</p>}
              </div>
            );
          })}
        </div>
        <p className="mt-3 text-[12px] leading-relaxed text-muted">
          GGUF and fp16 files only — this Mac's Metal backend can't load fp8 models. Downloads come straight from Hugging Face into the SSD folders the engine reads through <span className="font-mono">extra_model_paths.yaml</span>.
        </p>
      </Section>

      <Confirm open={!!confirm} title="Download model?" confirm={`Download ${confirm ? fmtGB(confirm.size_bytes) : ""}`}
        body={confirm && <>
          <p className="mb-2"><span className="text-ink">{confirm.filename}</span></p>
          <p className="font-mono text-[12px]">from huggingface.co/{confirm.repo}</p>
          <p className="mt-3">Saves to the SSD in <span className="font-mono">{confirm.folder}/</span>. Large files take a while; you can keep using the Studio.</p>
        </>}
        onCancel={() => setConfirm(null)}
        onConfirm={async () => {
          const m = confirm!; setConfirm(null);
          try { await api.download(m.id); toast(`Downloading ${m.label}…`); load(); }
          catch (e) { toast((e as Error).message, "error"); }
        }} />
    </div>
  );
}

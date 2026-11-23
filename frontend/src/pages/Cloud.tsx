import { Cloud, Copy, FolderSearch, ImagePlus, KeyRound, Library as LibraryIcon, Loader2, RotateCcw, Send, Square, Star, Trash2, Upload as UploadIcon } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { LensPanel } from "../components/LensPanel";
import { Confirm, Modal, Section } from "../components/ui";
import { api, fmtUSD, takeCost, timeAgo, type CloudInfo, type Job, type ProviderId, type Take, type Upload } from "../lib/api";
import { useStudio } from "../lib/store";

interface Frame extends Upload { source_job_id?: string | null; source_time?: number | null }

const STATUS_LABEL: Record<string, string> = {
  sending: "Sending", queued: "In the provider's queue", running: "Rendering", done: "Done", failed: "Failed", cancelled: "Stopped",
};

/** Cloud shots: a Studio frame + the LENS prompt, sent to Seedance 2.5 or Kling 3.0 through fal.ai or
 *  Replicate with Daniel's own key. Every take is logged with its prompt, model and estimated cost. */
export default function CloudShots() {
  const { projects, draft, setDraft, takes: live, toast, go } = useStudio();
  const [info, setInfo] = useState<CloudInfo | null>(null);
  const [project, setProject] = useState("");
  const [frame, setFrame] = useState<Frame | null>(null);
  const [prompt, setPrompt] = useState("");
  const [lockSuffix, setLockSuffix] = useState("");
  const [modelId, setModelId] = useState("seedance-2.5");
  const [provider, setProvider] = useState<ProviderId>("replicate");
  const [duration, setDuration] = useState(5);
  const [resolution, setResolution] = useState("1080p");
  const [audio, setAudio] = useState(false);
  const [list, setList] = useState<Take[] | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [picker, setPicker] = useState<{ open: boolean; job?: Job | null }>({ open: false });
  const [toDelete, setToDelete] = useState<Take | null>(null);
  const [sending, setSending] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const refreshInfo = useCallback(() => { api.cloud().then(setInfo).catch(e => toast((e as Error).message, "error")); }, [toast]);
  useEffect(refreshInfo, [refreshInfo]);
  useEffect(() => { if (!project && projects.length) setProject(projects[0].name); }, [projects, project]);

  // Pick the provider that has a key, so the screen opens ready to send.
  useEffect(() => {
    if (!info) return;
    if (!info.keys[provider].saved) {
      const other: ProviderId = provider === "fal" ? "replicate" : "fal";
      if (info.keys[other].saved) setProvider(other);
    }
  }, [info]); // eslint-disable-line react-hooks/exhaustive-deps

  // Arriving from the Library ("Cloud shot"): its opening frame becomes frame one.
  useEffect(() => {
    if (draft?.kind !== "cloud" || !draft.source) return;
    const src = draft.source;
    if (draft.project) setProject(draft.project);
    if (draft.prompt) setPrompt(draft.prompt);
    setDraft(null);
    api.grabFrame(src.job_id, src.seconds)
      .then(f => setFrame({ ...f, source_job_id: src.job_id, source_time: src.seconds }))
      .catch(e => toast((e as Error).message, "error"));
  }, [draft, setDraft, toast]);

  const loadTakes = useCallback(() => { api.takes(project || undefined).then(setList).catch(() => setList([])); }, [project]);
  useEffect(loadTakes, [loadTakes]);
  // Live updates from the backend replace the listed copy of a take.
  const takes = useMemo(() => {
    const byId = new Map((list ?? []).map(t => [t.id, t]));
    Object.values(live).forEach(t => { if (!project || t.project === project) byId.set(t.id, t); });
    return [...byId.values()].filter(t => (t.status as string) !== "deleted").sort((a, b) => b.created_at - a.created_at);
  }, [list, live, project]);
  const doneCount = takes.filter(t => t.status === "done").length;
  useEffect(() => { api.spend().then(s => setInfo(i => (i ? { ...i, spend: s } : i))).catch(() => {}); }, [doneCount]);

  const model = info?.models.find(m => m.id === modelId);
  useEffect(() => {
    if (!model) return;
    if (!model.durations.includes(duration)) setDuration(model.default_duration);
    if (!model.resolutions.includes(resolution)) setResolution(model.default_resolution);
    if (!model.providers[provider]) setProvider(Object.keys(model.providers)[0] as ProviderId);
  }, [model]); // eslint-disable-line react-hooks/exhaustive-deps

  const fullPrompt = [prompt.trim(), lockSuffix].filter(Boolean).join(" ");
  const cost = takeCost(model, provider, duration, resolution, audio);
  const keySaved = !!info?.keys[provider].saved;
  const providerLabel = info?.providers[provider].label ?? provider;
  const missing = !keySaved ? `Add your ${providerLabel} key in Settings first.` : !frame ? "Pick the first frame." :
    !fullPrompt ? "Write the shot prompt." : !project ? "Pick a project." : cost == null ? "No price for this choice in cloud.json." : null;

  const onUpload = async (f: File | undefined) => {
    if (!f) return;
    try { setFrame({ ...(await api.upload(f)), source_job_id: null, source_time: null }); }
    catch (e) { toast((e as Error).message, "error"); }
  };

  const send = async () => {
    setConfirmOpen(false);
    if (!frame || cost == null) return;
    setSending(true);
    try {
      const t = await api.sendTake({
        project, provider, model: modelId, prompt: fullPrompt, duration, resolution, audio,
        frame_path: frame.path, confirmed_cost: cost, source_job_id: frame.source_job_id ?? null, source_time: frame.source_time ?? null,
      });
      setList(l => [t, ...(l ?? [])]);
      toast(`Sent to ${model?.label}. It usually takes a few minutes.`);
    } catch (e) {
      toast((e as Error).message, "error");
      refreshInfo();
    } finally { setSending(false); }
  };

  const resend = (t: Take) => {
    setModelId(t.model); setProvider(t.provider); setDuration(t.duration); setResolution(t.resolution); setAudio(t.audio);
    setPrompt(t.prompt);
    if (t.frame_url) setFrame({ path: t.frame_path, url: t.frame_url, width: 0, height: 0, orientation: "landscape", source_job_id: t.source_job_id, source_time: t.source_time });
    window.scrollTo({ top: 0, behavior: "smooth" });
    toast("Loaded that take's frame, prompt and settings. The LENS locks will be added again unless you turn them off.", "info");
  };

  const patchTake = (t: Take) => setList(l => l?.map(x => (x.id === t.id ? t : x)) ?? null);

  if (!info) return <div className="p-10 text-muted">Loading…</div>;
  const noKeys = !info.keys.fal.saved && !info.keys.replicate.saved;

  return (
    <div className="mx-auto grid max-w-[1400px] grid-cols-1 gap-8 px-10 py-8 xl:grid-cols-[minmax(0,1fr)_420px]">
      <div className="flex flex-col gap-8">
        {noKeys && (
          <div className="card flex items-center justify-between gap-4 border-accent/40 p-5">
            <div>
              <p className="font-semibold">Add an API key to start.</p>
              <p className="text-sm text-ink-2">Paste your fal.ai or Replicate key in Settings. It stays on this Mac.</p>
            </div>
            <button className="btn btn-primary" onClick={() => go("settings")}><KeyRound size={15} />Open Settings</button>
          </div>
        )}

        <Section label="1 · First frame">
          <div className="card grid grid-cols-1 gap-5 p-5 md:grid-cols-[minmax(0,1fr)_220px]">
            <div className="flex aspect-video items-center justify-center overflow-hidden rounded-[3px] bg-black/40">
              {frame ? <img src={frame.url} alt="First frame" className="h-full w-full object-contain" />
                : <p className="px-6 text-center text-sm text-muted">The frame the shot starts from. Grab one from a render (its opening frame is a great start) or upload a still.</p>}
            </div>
            <div className="flex flex-col gap-2">
              <button className="btn btn-primary" onClick={() => setPicker({ open: true })}><LibraryIcon size={15} />From the Library</button>
              <button className="btn btn-secondary" onClick={() => fileRef.current?.click()}><UploadIcon size={15} />Upload a still</button>
              <input ref={fileRef} type="file" accept="image/*" hidden onChange={e => onUpload(e.target.files?.[0])} />
              {frame && <p className="mt-1 text-[12px] text-muted">{frame.width ? `${frame.width}×${frame.height}. ` : ""}The model renders at {resolution} from it; a small frame is fine.</p>}
            </div>
          </div>
        </Section>

        <Section label="2 · Shot prompt">
          <div className="flex flex-col gap-3">
            <LensPanel kind="video" project={project} onFill={setPrompt} onAppend={t => setPrompt(p => `${p.trim()} ${t}`.trim())} onLocks={setLockSuffix} />
            <textarea className="field min-h-[120px]" value={prompt} onChange={e => setPrompt(e.target.value)}
              placeholder="What happens in the shot, and how the camera moves. The LENS locks are added after it." />
            {fullPrompt && fullPrompt !== prompt.trim() && (
              <div className="card p-4">
                <div className="mb-1.5 flex items-center justify-between">
                  <span className="eyebrow">What the model reads</span>
                  <button className="btn btn-ghost px-2 py-0.5 text-[11px]" onClick={() => navigator.clipboard.writeText(fullPrompt).then(() => toast("Prompt copied."))}><Copy size={12} />Copy</button>
                </div>
                <p className="text-[12px] leading-relaxed text-ink-2">{fullPrompt}</p>
              </div>
            )}
          </div>
        </Section>

        <Section label="Take library">
          {takes.length === 0
            ? <div className="card p-8 text-center text-sm text-muted">No cloud takes in {project || "this project"} yet. Each one lands here with its prompt, model and cost.</div>
            : <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                {takes.map(t => <TakeCard key={t.id} t={t} info={info}
                  onStar={() => api.favoriteTake(t.id, !t.favorite).then(patchTake).catch(e => toast(e.message, "error"))}
                  onStop={() => api.cancelTake(t.id).then(patchTake).catch(e => toast(e.message, "error"))}
                  onResend={() => resend(t)}
                  onReveal={() => api.revealTake(t.id).catch(e => toast(e.message, "error"))}
                  onDelete={() => setToDelete(t)}
                  onCopy={() => navigator.clipboard.writeText(t.prompt).then(() => toast("Prompt copied."))} />)}
              </div>}
        </Section>
      </div>

      <div className="flex flex-col gap-6">
        <Section label="3 · Model">
          <div className="card flex flex-col gap-4 p-5">
            <div>
              <label className="mb-1.5 block text-sm text-ink-2">Project</label>
              <select className="field" value={project} onChange={e => setProject(e.target.value)}>
                {projects.map(p => <option key={p.name}>{p.name}</option>)}
              </select>
            </div>
            <div className="grid grid-cols-2 gap-2">
              {info.models.map(m => (
                <button key={m.id} onClick={() => setModelId(m.id)}
                  className={`rounded-[3px] border p-3 text-left ${m.id === modelId ? "border-accent bg-surface-2" : "border-hairline hover:border-ink-2"}`}>
                  <div className="font-semibold">{m.label}</div>
                </button>
              ))}
            </div>
            {model && <p className="text-[12px] text-muted">{model.note}</p>}
            <div>
              <label className="mb-1.5 block text-sm text-ink-2">Through</label>
              <div className="grid grid-cols-2 gap-2">
                {(Object.keys(info.providers) as ProviderId[]).filter(p => model?.providers[p]).map(p => (
                  <button key={p} onClick={() => setProvider(p)}
                    className={`rounded-[3px] border px-3 py-2 text-left text-sm ${p === provider ? "border-accent bg-surface-2" : "border-hairline hover:border-ink-2"}`}>
                    {info.providers[p].label}
                    <span className={`ml-2 text-[11px] ${info.keys[p].saved ? "text-ok" : "text-muted"}`}>{info.keys[p].saved ? "key saved" : "no key"}</span>
                  </button>
                ))}
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="mb-1.5 block text-sm text-ink-2">Length</label>
                <select className="field" value={duration} onChange={e => setDuration(Number(e.target.value))}>
                  {model?.durations.map(d => <option key={d} value={d}>{d} seconds</option>)}
                </select>
              </div>
              <div>
                <label className="mb-1.5 block text-sm text-ink-2">Resolution</label>
                <select className="field" value={resolution} onChange={e => setResolution(e.target.value)}>
                  {model?.resolutions.map(r => <option key={r}>{r}</option>)}
                </select>
              </div>
            </div>
            {model?.audio && (
              <label className="flex items-center gap-2 text-sm text-ink-2">
                <input type="checkbox" checked={audio} onChange={e => setAudio(e.target.checked)} />
                Generate sound with the shot
              </label>
            )}
          </div>
        </Section>

        <div className="card sticky top-[150px] flex flex-col gap-3 p-5">
          <div className="flex items-baseline justify-between">
            <span className="eyebrow">This take</span>
            <span className="display wf-grad-text text-[30px] normal-case">{fmtUSD(cost)}</span>
          </div>
          <p className="text-[12px] text-muted">Estimate from {providerLabel}'s price list as of {info.checked}. Your {providerLabel} bill is the final word.</p>
          <button className="btn btn-primary" disabled={!!missing || sending} onClick={() => setConfirmOpen(true)}>
            {sending ? <Loader2 size={15} className="animate-spin" /> : <Send size={15} />}Send to {model?.label}
          </button>
          {missing && <p className="text-[12px] text-warn">{missing}</p>}
          <div className="wf-hairline-grad my-1" />
          <dl className="grid grid-cols-2 gap-y-1 text-[13px]">
            <dt className="text-muted">Today</dt><dd className="text-right text-ink-2">{fmtUSD(info.spend.today)} · {info.spend.today_takes} takes</dd>
            <dt className="text-muted">This month</dt><dd className="text-right text-ink-2">{fmtUSD(info.spend.month)} · {info.spend.month_takes} takes</dd>
          </dl>
        </div>
      </div>

      <Confirm open={confirmOpen} title={`Send to ${model?.label}?`} confirm={`Send · ${fmtUSD(cost)}`}
        body={<>This spends about <b>{fmtUSD(cost)}</b> of your {providerLabel} credit: {duration} seconds at {resolution}{audio ? " with sound" : ", no sound"}, in {project}. A take that {providerLabel} refuses isn't charged.</>}
        onCancel={() => setConfirmOpen(false)} onConfirm={send} />

      <Confirm open={!!toDelete} title="Move this take to Trash?" danger confirm="Move to Trash"
        body="The video, its thumbnail and its settings file go to the macOS Trash. The cost already spent stays in your totals."
        onCancel={() => setToDelete(null)}
        onConfirm={() => { const t = toDelete; setToDelete(null); if (t) api.deleteTake(t.id).then(() => setList(l => l?.filter(x => x.id !== t.id) ?? null)).catch(e => toast(e.message, "error")); }} />

      <FramePicker open={picker.open} project={project} start={picker.job ?? null} onClose={() => setPicker({ open: false })}
        onPick={async (job, seconds) => {
          try {
            const f = await api.grabFrame(job.id, seconds);
            setFrame({ ...f, source_job_id: job.id, source_time: seconds });
            setPicker({ open: false });
          } catch (e) { toast((e as Error).message, "error"); }
        }} />
    </div>
  );
}

function TakeCard({ t, info, onStar, onStop, onResend, onReveal, onDelete, onCopy }: {
  t: Take; info: CloudInfo; onStar: () => void; onStop: () => void; onResend: () => void; onReveal: () => void; onDelete: () => void; onCopy: () => void;
}) {
  const active = t.status === "sending" || t.status === "queued" || t.status === "running";
  const label = info.models.find(m => m.id === t.model)?.label ?? t.model;
  return (
    <div className="card overflow-hidden">
      <div className="relative aspect-video bg-black/40">
        {t.status === "done" && t.video_url
          ? <video src={t.video_url} poster={t.thumb_url ?? undefined} controls className="h-full w-full object-contain" />
          : t.thumb_url && <img src={t.thumb_url} alt="" className="h-full w-full object-contain opacity-60" />}
        {t.status !== "done" && (
          <div className="absolute inset-0 flex items-center justify-center gap-2 bg-black/40 text-sm">
            {active && <Loader2 size={16} className="animate-spin text-accent" />}
            <span className={t.status === "failed" ? "text-bad" : "text-ink"}>{STATUS_LABEL[t.status] ?? t.status}</span>
          </div>
        )}
      </div>
      <div className="flex flex-col gap-2 p-4">
        <div className="flex items-center justify-between gap-2 text-[13px]">
          <span className="font-semibold">{label}</span>
          <span className="text-muted">{info.providers[t.provider]?.label} · {t.resolution} · {t.duration}s{t.audio ? " · sound" : ""} · {fmtUSD(t.est_cost)}</span>
        </div>
        <p className="line-clamp-3 text-[12px] leading-relaxed text-ink-2" title={t.prompt}>{t.prompt}</p>
        {t.error && <p className="text-[12px] text-bad">{t.error}</p>}
        <p className="text-[11px] text-muted">{timeAgo(t.created_at)}</p>
        <div className="flex flex-wrap gap-1">
          <button className={`btn btn-ghost px-2 ${t.favorite ? "text-accent" : ""}`} onClick={onStar} title="Circle this take"><Star size={15} fill={t.favorite ? "currentColor" : "none"} /></button>
          <button className="btn btn-ghost px-2" onClick={onCopy} title="Copy prompt"><Copy size={15} /></button>
          <button className="btn btn-ghost px-2" onClick={onResend} title="Load this take's frame, prompt and settings"><RotateCcw size={15} /></button>
          {t.file_exists && <button className="btn btn-ghost px-2" onClick={onReveal} title="Show in Finder"><FolderSearch size={15} /></button>}
          {active
            ? <button className="btn btn-ghost px-2 text-bad" onClick={onStop} title="Stop this take"><Square size={15} /></button>
            : <button className="btn btn-ghost px-2" onClick={onDelete} title="Move to Trash"><Trash2 size={15} /></button>}
        </div>
      </div>
    </div>
  );
}

function FramePicker({ open, project, start, onClose, onPick }: {
  open: boolean; project: string; start: Job | null; onClose: () => void; onPick: (job: Job, seconds: number) => void;
}) {
  const [items, setItems] = useState<Job[] | null>(null);
  const [job, setJob] = useState<Job | null>(start);
  const videoRef = useRef<HTMLVideoElement>(null);
  useEffect(() => { if (open) { setJob(start); api.library({ project: project || undefined }).then(setItems).catch(() => setItems([])); } }, [open, project, start]);
  return (
    <Modal open={open} onClose={onClose} wide>
      <div className="p-6">
        <h3 className="display mb-4 text-2xl">{job ? "Pick the frame" : `Frames from ${project}`}</h3>
        {!job && (items === null ? <p className="text-muted">Loading…</p> : items.length === 0
          ? <p className="text-sm text-muted">Nothing in this project's Library yet.</p>
          : <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              {items.filter(j => j.file_exists).map(j => (
                <button key={j.id} className="card overflow-hidden text-left hover:border-accent" onClick={() => (j.kind === "image" ? onPick(j, 0) : setJob(j))}>
                  {j.thumb_url && <img src={j.thumb_url} alt="" className="aspect-video w-full object-cover" />}
                  <p className="line-clamp-2 p-2 text-[11px] text-ink-2">{j.kind === "image" ? <ImagePlus size={11} className="mr-1 inline" /> : <Cloud size={11} className="mr-1 inline" />}{j.prompt}</p>
                </button>
              ))}
            </div>)}
        {job && (
          <div className="flex flex-col gap-3">
            <video ref={videoRef} src={job.video_url ?? undefined} controls className="max-h-[60vh] w-full bg-black" preload="auto" />
            <p className="text-[12px] text-muted">Scrub to the frame you want, then use it. The opening frame is usually the cleanest.</p>
            <div className="flex justify-end gap-2">
              <button className="btn btn-ghost" onClick={() => setJob(null)}>Back</button>
              <button className="btn btn-secondary" onClick={() => onPick(job, 0)}>Use the opening frame</button>
              <button className="btn btn-primary" onClick={() => onPick(job, videoRef.current?.currentTime ?? 0)}>Use this frame</button>
            </div>
          </div>
        )}
      </div>
    </Modal>
  );
}

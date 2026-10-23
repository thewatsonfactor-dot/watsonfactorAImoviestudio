import { ArrowDown, ArrowUp, Clapperboard, Play, RotateCcw, Square, Trash2, X } from "lucide-react";
import { useState } from "react";
import { api, fmtDuration, imageDraftFrom, jobTag, orientationOf, timeAgo, type Job } from "../lib/api";
import { useStudio } from "../lib/store";
import { Empty, Section } from "../components/ui";

export default function Renders() {
  const { jobs, queueIds, queueBlocked, go, toast, presets } = useStudio();
  const running = Object.values(jobs).filter(j => j.status === "running");
  const queued = queueIds.map(id => jobs[id]).filter(Boolean);
  const recent = Object.values(jobs)
    .filter(j => ["done", "failed", "cancelled"].includes(j.status) && (j.finished_at ?? 0) > Date.now() / 1000 - 86400)
    .sort((a, b) => (b.finished_at ?? 0) - (a.finished_at ?? 0)).slice(0, 8);

  const move = async (id: string, dir: -1 | 1) => {
    const ids = [...queueIds];
    const i = ids.indexOf(id), j = i + dir;
    if (j < 0 || j >= ids.length) return;
    [ids[i], ids[j]] = [ids[j], ids[i]];
    await api.reorder(ids);
  };
  const cancel = async (j: Job) => {
    try { await api.cancel(j.id); toast(j.status === "running" ? "Stopping the render…" : "Removed from the queue."); }
    catch (e) { toast((e as Error).message, "error"); }
  };

  if (!running.length && !queued.length && !recent.length) {
    return (
      <div className="mx-auto max-w-[1100px] px-10 py-8">
        <Empty icon={<Clapperboard size={40} />} title="Nothing rendering" body="Queue a render from Create and it shows up here with live progress."
          action={<button className="btn btn-primary" onClick={() => go("create")}>Go to Create</button>} />
      </div>
    );
  }

  return (
    <div className="mx-auto flex max-w-[1100px] flex-col gap-8 px-10 py-8">
      {queueBlocked && (queued.length > 0) && (
        <div className="rounded-[3px] border border-bad/40 bg-bad/10 px-4 py-3 text-sm text-ink">
          <span className="font-semibold text-bad">Queue paused.</span> {queueBlocked}
        </div>
      )}

      <Section label="Now rendering">
        {running.length ? running.map(j => <LiveCard key={j.id} job={j} onCancel={() => cancel(j)} label={j.kind === "image" ? "Image" : presets?.presets[j.preset]?.label} />)
          : <div className="card px-5 py-6 text-sm text-muted">{queued.length ? "Starting the next job…" : "The engine is idle."}</div>}
      </Section>

      {queued.length > 0 && (
        <Section label={`Up next · ${queued.length}`}>
          <div className="card divide-y divide-hairline">
            {queued.map((j, i) => (
              <div key={j.id} className="flex items-center gap-4 px-4 py-3">
                <span className="display w-6 text-xl text-muted">{i + 1}</span>
                {j.input_url && <img src={j.input_url} className="h-12 w-20 rounded-[2px] object-cover" alt="" />}
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm">{j.prompt}</p>
                  <p className="font-mono text-[11px] text-muted">{j.project} · {jobTag(j, presets)} · {j.width}×{j.height}</p>
                </div>
                <button className="btn btn-ghost" disabled={i === 0} onClick={() => move(j.id, -1)} title="Move up"><ArrowUp size={16} /></button>
                <button className="btn btn-ghost" disabled={i === queued.length - 1} onClick={() => move(j.id, 1)} title="Move down"><ArrowDown size={16} /></button>
                <button className="btn btn-ghost" onClick={() => cancel(j)} title="Remove"><X size={16} /></button>
              </div>
            ))}
          </div>
        </Section>
      )}

      {recent.length > 0 && (
        <Section label="Last 24 hours">
          <div className="flex flex-col gap-2.5">
            {recent.map(j => <RecentRow key={j.id} job={j} />)}
          </div>
        </Section>
      )}
    </div>
  );
}

function LiveCard({ job, onCancel, label }: { job: Job; onCancel: () => void; label?: string }) {
  const live = job.live;
  const pct = live?.percent ?? 0;
  return (
    <div className="card wf-grad-border flex gap-6 p-5">
      {job.input_url && <img src={job.input_url} alt="" className="h-[124px] w-[220px] shrink-0 rounded-[3px] object-cover" />}
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <p className="eyebrow mb-1">{job.project} · {label ?? job.preset} · {job.width}×{job.height}</p>
            <p className="line-clamp-2 text-[15px] text-ink">{job.prompt}</p>
          </div>
          <button className="btn btn-danger shrink-0" onClick={onCancel}><Square size={14} />Cancel</button>
        </div>
        <div className="mt-auto pt-4">
          <div className="mb-2 flex items-end justify-between">
            <span className="display text-2xl">{live?.label ?? "Starting…"}</span>
            <span className="display wf-grad-text text-3xl">{Math.round(pct)}%</span>
          </div>
          <div className={`progress ${!live || live.stage === "load" || live.stage === "submitting" ? "indeterminate" : ""}`}><div style={{ width: `${pct}%` }} /></div>
          <div className="mt-2 flex justify-between font-mono text-[11px] text-muted">
            <span>Elapsed {fmtDuration(live?.elapsed)}</span>
            <span>{live?.eta_seconds != null ? `About ${fmtDuration(live.eta_seconds)} left` : "Estimating time left…"}</span>
          </div>
        </div>
      </div>
    </div>
  );
}

function RecentRow({ job }: { job: Job }) {
  const { toast, setDraft, go, forget } = useStudio();
  const [open, setOpen] = useState(false);
  const failed = job.status === "failed";
  return (
    <div className={`card px-4 py-3 ${failed ? "border-bad/35" : ""}`}>
      <div className="flex items-center gap-4">
        {job.thumb_url && <img src={job.thumb_url} className="h-12 w-20 rounded-[2px] object-cover" alt="" />}
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm">{job.prompt}</p>
          <p className={`text-[12px] ${failed ? "text-bad" : "text-muted"}`}>
            {job.status === "done" && <>Done in {fmtDuration(job.render_seconds)} · {timeAgo(job.finished_at)}</>}
            {job.status === "cancelled" && <>Cancelled · {timeAgo(job.finished_at)}</>}
            {failed && job.error}
          </p>
        </div>
        {job.status === "done" && <button className="btn btn-secondary text-xs" onClick={() => go("library")}><Play size={14} />Library</button>}
        {job.status !== "done" && (
          <>
            {failed && job.error_detail && <button className="btn btn-ghost text-xs" onClick={() => setOpen(o => !o)}>{open ? "Hide" : "Details"}</button>}
            <button className="btn btn-secondary text-xs" onClick={() => {
              if (job.kind === "image") { setDraft(imageDraftFrom(job)); go("image"); return; }
              setDraft({ upload: job.input_url ? { path: job.input_path, url: job.input_url, width: job.width, height: job.height, orientation: orientationOf(job.width, job.height) } : undefined,
                prompt: job.prompt, negative: job.negative ?? undefined, project: job.project, preset: job.preset, length: job.length, seed: job.seed });
              go("create");
            }}><RotateCcw size={14} />Try again</button>
            <button className="btn btn-ghost" title="Dismiss" onClick={() => api.dismiss(job.id).then(() => forget(job.id)).catch(e => toast(e.message, "error"))}><Trash2 size={14} /></button>
          </>
        )}
      </div>
      {open && <pre className="scroll-thin mt-3 max-h-56 overflow-auto rounded-[3px] bg-ground p-3 font-mono text-[11px] whitespace-pre-wrap text-ink-2">{job.error_detail}</pre>}
    </div>
  );
}

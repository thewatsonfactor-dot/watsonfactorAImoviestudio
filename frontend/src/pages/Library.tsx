import { Clapperboard, Copy, Dice5, FolderSearch, Heart, ImagePlus, Library as LibraryIcon, Search, Trash2, Wand2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api, fmtDuration, imageDraftFrom, jobTag, orientationOf, timeAgo, type Job } from "../lib/api";
import { useStudio } from "../lib/store";
import { Confirm, Empty, Modal } from "../components/ui";

export default function Library() {
  const { projects, presets, libraryVersion, toast, go, setDraft } = useStudio();
  const [items, setItems] = useState<Job[] | null>(null);
  const [project, setProject] = useState("");
  const [favorites, setFavorites] = useState(false);
  const [preset, setPreset] = useState("");
  const [kind, setKind] = useState("");
  const [q, setQ] = useState("");
  const [open, setOpen] = useState<Job | null>(null);
  const [toDelete, setToDelete] = useState<Job | null>(null);

  useEffect(() => {
    const t = setTimeout(() => {
      api.library({ project, favorites, preset, q, kind }).then(setItems).catch(e => toast(e.message, "error"));
    }, q ? 250 : 0);
    return () => clearTimeout(t);
  }, [project, favorites, preset, q, kind, libraryVersion, toast]);

  const patch = (j: Job) => {
    setItems(list => list?.map(x => (x.id === j.id ? j : x)) ?? null);
    if (open?.id === j.id) setOpen(j);
  };

  const act = {
    favorite: (j: Job) => api.favorite(j.id, !j.favorite).then(patch).catch(e => toast(e.message, "error")),
    reroll: (j: Job) => api.reroll(j.id).then(() => toast(j.kind === "image" ? "Re-roll queued — same prompt and references, new seed." : "Re-roll queued — same shot, new seed.")).catch(e => toast(e.message, "error")),
    // Image → video: copy the still into the keyframe folder and open Create with it.
    animate: async (j: Job) => {
      try {
        const kf = await api.toKeyframe(j.id);
        setDraft({ upload: kf, prompt: "", project: j.project });
        go("create");
      } catch (e) { toast((e as Error).message, "error"); }
    },
    asReference: (j: Job) => {
      if (!j.output_path || !j.video_url) return;
      setDraft({ kind: "image", project: j.project, refs: [{ path: j.output_path, url: j.video_url, width: j.width, height: j.height, orientation: orientationOf(j.width, j.height) }] });
      go("image");
    },
    remix: (j: Job) => {
      if (j.kind === "image") { setDraft({ ...imageDraftFrom(j), seed: j.seed }); go("image"); return; }
      setDraft({
        upload: j.input_url ? { path: j.input_path, url: j.input_url, width: j.width, height: j.height, orientation: orientationOf(j.width, j.height) } : undefined,
        prompt: j.prompt, negative: j.negative ?? undefined, project: j.project, preset: j.preset, length: j.length, seed: j.seed,
      });
      go("create");
    },
    copy: (j: Job) => navigator.clipboard.writeText(j.prompt).then(() => toast("Prompt copied.")),
    reveal: (j: Job) => api.reveal(j.id).catch(e => toast(e.message, "error")),
    remove: async (j: Job) => {
      try {
        await api.remove(j.id);
        setItems(list => list?.filter(x => x.id !== j.id) ?? null);
        setOpen(null);
        toast("Moved to the Trash.");
      } catch (e) { toast((e as Error).message, "error"); }
    },
  };

  return (
    <div className="mx-auto max-w-[1400px] px-10 py-8">
      <div className="mb-6 flex flex-wrap items-center gap-3">
        <select className="field w-auto min-w-[200px]" value={project} onChange={e => setProject(e.target.value)}>
          <option value="">All projects</option>
          {projects.map(p => <option key={p.name} value={p.name}>{p.name}</option>)}
        </select>
        <select className="field w-auto min-w-[160px]" value={kind} onChange={e => setKind(e.target.value)}>
          <option value="">Videos & images</option>
          <option value="video">Videos</option>
          <option value="image">Images</option>
        </select>
        <select className="field w-auto min-w-[160px]" value={preset} onChange={e => setPreset(e.target.value)}>
          <option value="">Any quality</option>
          {presets && Object.entries(presets.presets).map(([k, d]) => <option key={k} value={k}>{d.label}</option>)}
        </select>
        <button className={`btn ${favorites ? "btn-primary" : "btn-secondary"}`} onClick={() => setFavorites(f => !f)}>
          <Heart size={16} fill={favorites ? "currentColor" : "none"} />Favorites
        </button>
        <div className="relative ml-auto w-full max-w-xs">
          <Search size={16} className="absolute top-1/2 left-3 -translate-y-1/2 text-muted" />
          <input className="field pl-9" placeholder="Search prompts" value={q} onChange={e => setQ(e.target.value)} />
        </div>
      </div>

      {items && items.length === 0 ? (
        <Empty icon={<LibraryIcon size={40} />} title={project || favorites || preset || q || kind ? "No matches" : "No renders yet"}
          body={project || favorites || preset || q || kind ? "Nothing matches these filters." : "Finished renders and images land here, filed by project, with everything needed to re-roll them."}
          action={!(project || favorites || preset || q || kind) && <button className="btn btn-primary" onClick={() => go("create")}>Make the first one</button>} />
      ) : (
        <div className="grid grid-cols-[repeat(auto-fill,minmax(280px,1fr))] gap-5">
          {items?.map(j => <Tile key={j.id} job={j} onOpen={() => setOpen(j)} onFav={() => act.favorite(j)} label={jobTag(j, presets)} />)}
        </div>
      )}

      <Modal open={!!open} onClose={() => setOpen(null)} wide>
        {open && (
          <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_340px]">
            <div className="flex items-center justify-center bg-[#02061a]">
              {open.file_exists && open.video_url
                ? (open.kind === "image"
                  ? <img key={open.id} src={open.video_url} alt={open.prompt} className="max-h-[78vh] w-full object-contain" />
                  : <video key={open.id} src={open.video_url} controls autoPlay loop className="max-h-[78vh] w-full" />)
                : <p className="p-10 text-sm text-muted">The {open.kind === "image" ? "image" : "video"} file isn't on the SSD right now.</p>}
            </div>
            <div className="flex flex-col gap-4 p-6">
              <div>
                <p className="eyebrow mb-1">{open.project}</p>
                <p className="text-[15px] leading-relaxed">{open.prompt}</p>
              </div>
              <dl className="grid grid-cols-2 gap-x-4 gap-y-2 font-mono text-[12px]">
                {(open.kind === "image"
                  ? [["Type", "Still image"], ["Size", `${open.width}×${open.height}`],
                     ["References", open.refs.length || "none"], ["Seed", open.seed],
                     ["Render", fmtDuration(open.render_seconds)], ["Made", timeAgo(open.finished_at)]]
                  : [["Quality", presets?.presets[open.preset]?.label ?? open.preset], ["Size", `${open.width}×${open.height}`],
                     ["Frames", `${open.frames} · ${presets?.fps ?? 16} fps`], ["Seed", open.seed],
                     ["Render", fmtDuration(open.render_seconds)], ["Made", timeAgo(open.finished_at)]]).map(([k, v]) => (
                  <div key={String(k)}><dt className="text-muted">{k}</dt><dd className="text-ink-2">{v}</dd></div>
                ))}
              </dl>
              {open.kind === "image" && open.file_exists && (
                <div className="grid grid-cols-2 gap-2">
                  <button className="btn btn-primary" onClick={() => act.animate(open)} title="Open this still in Create as the keyframe"><Clapperboard size={15} />Animate</button>
                  <button className="btn btn-secondary" onClick={() => act.asReference(open)} title="Start a new image with this one as Picture 1"><ImagePlus size={15} />Use as reference</button>
                </div>
              )}
              <div className="mt-2 grid grid-cols-2 gap-2">
                <button className={`btn ${open.favorite ? "btn-primary" : "btn-secondary"}`} onClick={() => act.favorite(open)}><Heart size={15} fill={open.favorite ? "currentColor" : "none"} />{open.favorite ? "Favorited" : "Favorite"}</button>
                <button className="btn btn-secondary" onClick={() => act.reroll(open)} title="Same everything, new seed"><Dice5 size={15} />Re-roll</button>
                <button className="btn btn-secondary" onClick={() => act.remix(open)} title={open.kind === "image" ? "Open in Image, pre-filled" : "Open in Create, pre-filled"}><Wand2 size={15} />Remix</button>
                <button className="btn btn-secondary" onClick={() => act.copy(open)}><Copy size={15} />Copy prompt</button>
                <button className="btn btn-secondary" onClick={() => act.reveal(open)}><FolderSearch size={15} />Show in Finder</button>
                <button className="btn btn-danger" onClick={() => setToDelete(open)}><Trash2 size={15} />Delete</button>
              </div>
            </div>
          </div>
        )}
      </Modal>

      <Confirm open={!!toDelete} title="Move to Trash?" danger confirm="Move to Trash"
        body={`The ${toDelete?.kind === "image" ? "image" : "video"}, its thumbnail and its settings file go to the macOS Trash. You can still restore them from there.`}
        onCancel={() => setToDelete(null)} onConfirm={() => { if (toDelete) act.remove(toDelete); setToDelete(null); }} />
    </div>
  );
}

function Tile({ job, onOpen, onFav, label }: { job: Job; onOpen: () => void; onFav: () => void; label?: string }) {
  const vid = useRef<HTMLVideoElement>(null);
  const [hover, setHover] = useState(false);
  return (
    <div className="card group overflow-hidden transition-colors hover:border-accent/50"
      onMouseEnter={() => { setHover(true); vid.current?.play().catch(() => {}); }}
      onMouseLeave={() => { setHover(false); if (vid.current) { vid.current.pause(); vid.current.currentTime = 0; } }}>
      <button className="relative block aspect-video w-full bg-[#02061a]" onClick={onOpen}>
        {job.thumb_url && <img src={job.thumb_url} alt="" className={`absolute inset-0 h-full w-full object-cover transition-opacity ${hover && job.file_exists && job.kind !== "image" ? "opacity-0" : ""}`} />}
        {job.kind !== "image" && job.file_exists && job.video_url && <video ref={vid} src={job.video_url} muted loop playsInline preload="none" className="absolute inset-0 h-full w-full object-cover" />}
        <span className="absolute bottom-2 left-2 rounded-[3px] bg-ground/85 px-2 py-0.5 font-mono text-[10px] tracking-wider text-ink-2">{label}</span>
        {!job.file_exists && <span className="absolute inset-0 flex items-center justify-center bg-ground/70 text-xs text-warn">File not on SSD</span>}
      </button>
      <div className="flex items-start gap-2 p-3">
        <div className="min-w-0 flex-1">
          <p className="line-clamp-2 text-[13px] leading-snug">{job.prompt}</p>
          <p className="mt-1 font-mono text-[10px] text-muted">{job.project} · {timeAgo(job.finished_at)}</p>
        </div>
        <button className={`btn btn-ghost p-1.5 ${job.favorite ? "text-pink" : ""}`} onClick={onFav} title="Favorite">
          <Heart size={16} fill={job.favorite ? "currentColor" : "none"} />
        </button>
      </div>
    </div>
  );
}

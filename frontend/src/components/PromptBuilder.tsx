import { ChevronDown, Plus, Trash2, X } from "lucide-react";
import { useEffect, useState } from "react";
import { api, type Picks, type PromptCategory, type PromptLibrary } from "../lib/api";
import { useStudio } from "../lib/store";

/** Shot recipe: one dropdown per category; picks are appended to the prompt as sentences.
 *  The parent owns `picks` and composes the final prompt with composePrompt(). */
export function PromptBuilder({ kind, picks, onPicks, onLibrary }: {
  kind: "video" | "image";
  picks: Picks;
  onPicks: (p: Picks) => void;
  onLibrary: (cats: PromptCategory[]) => void;
}) {
  const { toast } = useStudio();
  const [lib, setLib] = useState<PromptLibrary | null>(null);
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState({ category: "", label: "", text: "" });

  const apply = (l: PromptLibrary) => { setLib(l); onLibrary(l[kind]); };
  useEffect(() => {
    api.promptLibrary().then(apply).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kind]);

  const cats = lib?.[kind] ?? [];
  if (!cats.length) return null;
  const used = Object.values(picks).filter(Boolean).length;

  const save = async () => {
    const category = draft.category || cats[0].id;
    try {
      const l = await api.addBlock({ kind, category, label: draft.label, text: draft.text });
      apply(l);
      const added = l[kind].find(c => c.id === category)?.options.filter(o => o.custom).pop();
      if (added) onPicks({ ...picks, [category]: added.id });
      setDraft({ category: "", label: "", text: "" });
      setAdding(false);
      toast(`Saved "${draft.label}" to ${l[kind].find(c => c.id === category)?.label ?? "your blocks"}.`);
    } catch (e) { toast((e as Error).message, "error"); }
  };

  const remove = async (catId: string, id: string) => {
    try {
      apply(await api.deleteBlock(id));
      const { [catId]: _gone, ...rest } = picks;
      onPicks(rest);
      toast("Block deleted.");
    } catch (e) { toast((e as Error).message, "error"); }
  };

  return (
    <div className="card p-4">
      <div className="mb-3 flex items-center justify-between">
        <span className="eyebrow">Shot recipe{used ? ` · ${used} picked` : ""}</span>
        <div className="flex gap-1">
          {used > 0 && <button className="btn btn-ghost text-xs" onClick={() => onPicks({})}><X size={13} />Clear</button>}
          <button className="btn btn-ghost text-xs" onClick={() => setAdding(a => !a)}><Plus size={13} />Add your own</button>
        </div>
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {cats.map(c => {
          const picked = c.options.find(o => o.id === picks[c.id]);
          const groups = [...new Set(c.options.map(o => o.group ?? ""))];
          return (
            <div key={c.id}>
              <label className="mb-1 block text-[12px] text-muted">{c.label}</label>
              <div className="flex gap-1.5">
                <div className="relative min-w-0 flex-1">
                  <select className="field appearance-none pr-8 text-sm" value={picks[c.id] ?? ""}
                    onChange={e => {
                      const v = e.target.value;
                      const next = { ...picks };
                      if (v) next[c.id] = v; else delete next[c.id];
                      onPicks(next);
                    }}>
                    <option value="">None</option>
                    {groups.map(g => {
                      const opts = c.options.filter(o => (o.group ?? "") === g);
                      const items = opts.map(o => <option key={o.id} value={o.id}>{o.label}</option>);
                      return g ? <optgroup key={g} label={g}>{items}</optgroup> : items;
                    })}
                  </select>
                  <ChevronDown size={14} className="pointer-events-none absolute top-1/2 right-3 -translate-y-1/2 text-muted" />
                </div>
                {picked?.custom && (
                  <button className="btn btn-ghost px-2" title="Delete this block" onClick={() => remove(c.id, picked.id)}><Trash2 size={14} /></button>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {adding && (
        <div className="mt-4 flex flex-col gap-2 border-t border-hairline pt-4">
          <div className="grid grid-cols-2 gap-2">
            <select className="field text-sm" value={draft.category || cats[0].id} onChange={e => setDraft(d => ({ ...d, category: e.target.value }))}>
              {cats.map(c => <option key={c.id} value={c.id}>{c.label}</option>)}
            </select>
            <input className="field text-sm" placeholder="Name, e.g. Slow creep in" maxLength={60}
              value={draft.label} onChange={e => setDraft(d => ({ ...d, label: e.target.value }))} />
          </div>
          <textarea className="field min-h-[70px] text-sm" maxLength={1200}
            placeholder="What it adds to the prompt, written as what's on screen. e.g. The camera creeps forward very slowly, almost unnoticeably, toward the subject's face."
            value={draft.text} onChange={e => setDraft(d => ({ ...d, text: e.target.value }))} />
          <div className="flex justify-end gap-2">
            <button className="btn btn-ghost text-xs" onClick={() => setAdding(false)}>Cancel</button>
            <button className="btn btn-primary text-xs" disabled={!draft.label.trim() || !draft.text.trim()} onClick={save}>Save block</button>
          </div>
        </div>
      )}
    </div>
  );
}

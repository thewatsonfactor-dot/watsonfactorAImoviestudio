import { X } from "lucide-react";
import { useEffect, type ReactNode } from "react";

export function StatCard({ value, caption, hint }: { value: ReactNode; caption: string; hint?: string }) {
  return (
    <div className="card px-5 py-4" title={hint}>
      <div className="display wf-grad-text text-[30px] normal-case">{value}</div>
      <div className="mt-1.5 text-[13px] text-muted">{caption}</div>
    </div>
  );
}

export function Section({ label, right, children }: { label: string; right?: ReactNode; children: ReactNode }) {
  return (
    <section>
      <div className="mb-2.5 flex items-center justify-between gap-3">
        <span className="eyebrow">{label}</span>
        {right}
      </div>
      {children}
    </section>
  );
}

export function Modal({ open, onClose, children, wide }: { open: boolean; onClose: () => void; children: ReactNode; wide?: boolean }) {
  useEffect(() => {
    if (!open) return;
    const on = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-[90] flex items-center justify-center bg-[#02061a]/80 p-6 backdrop-blur-sm" onClick={onClose}>
      <div className={`card relative max-h-[92vh] w-full overflow-y-auto bg-surface-2 ${wide ? "max-w-6xl" : "max-w-md"}`} onClick={e => e.stopPropagation()}>
        <button className="btn btn-ghost absolute top-2 right-2 z-10" onClick={onClose} aria-label="Close"><X size={18} /></button>
        {children}
      </div>
    </div>
  );
}

export function Confirm({ open, title, body, confirm, danger, onConfirm, onCancel }: {
  open: boolean; title: string; body: ReactNode; confirm: string; danger?: boolean;
  onConfirm: () => void; onCancel: () => void;
}) {
  return (
    <Modal open={open} onClose={onCancel}>
      <div className="p-6">
        <h3 className="display mb-3 text-2xl">{title}</h3>
        <div className="mb-6 text-sm leading-relaxed text-ink-2">{body}</div>
        <div className="flex justify-end gap-2">
          <button className="btn btn-secondary" onClick={onCancel}>Cancel</button>
          <button className={`btn ${danger ? "btn-danger" : "btn-primary"}`} onClick={onConfirm}>{confirm}</button>
        </div>
      </div>
    </Modal>
  );
}

export function Empty({ icon, title, body, action }: { icon: ReactNode; title: string; body: string; action?: ReactNode }) {
  return (
    <div className="card flex flex-col items-center px-8 py-16 text-center">
      <div className="mb-4 text-muted">{icon}</div>
      <h3 className="display mb-2 text-2xl">{title}</h3>
      <p className="max-w-md text-sm text-muted">{body}</p>
      {action && <div className="mt-6">{action}</div>}
    </div>
  );
}

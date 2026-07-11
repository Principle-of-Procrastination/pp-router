import { useEffect, useRef, useState } from "react";
import type { ModelInfo } from "../api";
import { TierBadge } from "./badges";

export default function ModelsPopover({
  models,
  error,
}: {
  models: ModelInfo[];
  error: string | null;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onDown(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex shrink-0 items-center gap-2 whitespace-nowrap rounded-full border border-line bg-surface/70 px-3.5 py-1.5 text-xs text-fg-muted transition-colors hover:border-accent/30 hover:text-fg"
      >
        模型
        <span className="font-mono text-[10px] text-fg-dim">{models.length}</span>
        <span
          className={`text-fg-dim transition-transform duration-200 ${
            open ? "rotate-180" : ""
          }`}
        >
          ▾
        </span>
      </button>

      {open && (
        <div className="absolute right-0 z-20 mt-2 w-80 max-w-[calc(100vw-2rem)] overflow-hidden rounded-2xl border border-line bg-surface shadow-2xl shadow-black/40">
          <div className="border-b border-line px-4 py-3 text-[10px] uppercase tracking-[0.2em] text-fg-dim">
            支持的模型 · 难度档
          </div>
          {error && <p className="px-4 py-3 text-xs text-[#e8a89c]">{error}</p>}
          {!error && models.length === 0 && (
            <p className="px-4 py-3 text-xs text-fg-dim">加载中…</p>
          )}
          <ul className="divide-y divide-line">
            {models.map((m) => (
              <li key={m.id} className="px-4 py-3">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-sm text-fg">{m.id}</span>
                  <div className="flex flex-wrap justify-end gap-1">
                    {m.tiers.map((t) => (
                      <TierBadge key={t} tier={t} />
                    ))}
                  </div>
                </div>
                <div className="mt-1 font-mono text-[11px] text-fg-dim">
                  {m.litellm_model}
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

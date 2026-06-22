import type { ModelInfo } from "../api";
import { TierBadge } from "./badges";

export default function ModelsPanel({
  models,
  error,
}: {
  models: ModelInfo[];
  error: string | null;
}) {
  return (
    <section className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
      <h2 className="mb-3 text-sm font-semibold text-slate-200">支持的模型</h2>
      {error && <p className="text-xs text-rose-400">{error}</p>}
      {!error && models.length === 0 && (
        <p className="text-xs text-slate-500">加载中…</p>
      )}
      <ul className="space-y-2">
        {models.map((m) => (
          <li key={m.id} className="rounded-lg bg-slate-800/50 p-2.5">
            <div className="flex items-center justify-between gap-2">
              <span className="font-mono text-sm text-slate-100">{m.id}</span>
              <div className="flex flex-wrap justify-end gap-1">
                {m.tiers.map((t) => (
                  <TierBadge key={t} tier={t} />
                ))}
              </div>
            </div>
            <div className="mt-1 font-mono text-[11px] text-slate-500">
              {m.litellm_model}
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

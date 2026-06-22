import { useCallback, useEffect, useState } from "react";
import { getHistory, type HistoryResponse } from "../api";
import { TierBadge } from "./badges";

export default function HistoryPanel({ version }: { version: number }) {
  const [data, setData] = useState<HistoryResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await getHistory(50));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load, version]);

  return (
    <section className="flex min-h-0 flex-1 flex-col rounded-xl border border-slate-800 bg-slate-900/50 p-4">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-slate-200">历史与用量</h2>
        <button
          onClick={load}
          className="rounded-md border border-slate-700 px-2 py-1 text-xs text-slate-300 hover:bg-slate-800"
        >
          {loading ? "刷新中…" : "刷新"}
        </button>
      </div>

      {error && <p className="text-xs text-rose-400">{error}</p>}

      {data && (
        <>
          <div className="mb-3 grid grid-cols-2 gap-2">
            <div className="rounded-lg bg-slate-800/50 p-2.5">
              <div className="text-lg font-semibold text-slate-100">
                {data.summary.total_requests}
              </div>
              <div className="text-[11px] text-slate-400">总请求数</div>
            </div>
            <div className="rounded-lg bg-slate-800/50 p-2.5">
              <div className="text-lg font-semibold text-slate-100">
                {data.summary.total_tokens.toLocaleString()}
              </div>
              <div className="text-[11px] text-slate-400">总 token</div>
            </div>
          </div>

          {Object.keys(data.summary.by_model).length > 0 && (
            <div className="mb-3 space-y-1">
              {Object.entries(data.summary.by_model).map(([model, stat]) => (
                <div
                  key={model}
                  className="flex items-center justify-between rounded-md bg-slate-800/30 px-2.5 py-1.5 text-xs"
                >
                  <span className="font-mono text-slate-200">{model}</span>
                  <span className="text-slate-400">
                    {stat.requests} 次 · {stat.total_tokens.toLocaleString()} tok
                  </span>
                </div>
              ))}
            </div>
          )}

          <div className="mb-1 text-[11px] font-medium uppercase tracking-wide text-slate-500">
            最近请求
          </div>
          <ul className="min-h-0 flex-1 space-y-2 overflow-y-auto">
            {data.items.length === 0 && (
              <li className="text-xs text-slate-500">暂无记录，先发起一次对话。</li>
            )}
            {data.items.map((it, i) => (
              <li key={i} className="rounded-lg bg-slate-800/50 p-2.5">
                <div className="truncate text-sm text-slate-100" title={it.query}>
                  {it.query}
                </div>
                <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[11px] text-slate-400">
                  <span className="font-mono text-slate-300">{it.model}</span>
                  {it.forced ? (
                    <span className="rounded bg-slate-700 px-1.5 py-0.5">forced</span>
                  ) : (
                    <TierBadge tier={it.tier} />
                  )}
                  <span className="text-slate-500">·</span>
                  <span>{it.usage.total_tokens} tok</span>
                  <span className="ml-auto text-slate-600">
                    {it.ts.replace("T", " ").slice(0, 19)}
                  </span>
                </div>
              </li>
            ))}
          </ul>
        </>
      )}
      {!data && !error && loading && (
        <p className="text-xs text-slate-500">加载中…</p>
      )}
    </section>
  );
}

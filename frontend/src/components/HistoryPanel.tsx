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
    <section className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-2xl bg-surface/70 ring-1 ring-line">
      <header className="flex items-center justify-between border-b border-line px-5 py-3.5">
        <span className="text-[11px] uppercase tracking-[0.2em] text-fg-dim">
          历史与用量
        </span>
        <button
          onClick={load}
          className="rounded-lg px-2.5 py-1 text-xs text-fg-dim transition-colors hover:bg-surface-2 hover:text-fg-muted"
        >
          {loading ? "刷新中…" : "刷新"}
        </button>
      </header>

      <div className="flex min-h-0 flex-1 flex-col px-5 py-4">
        {error && <p className="text-xs text-[#e8a89c]">{error}</p>}

        {data && (
          <>
            <div className="flex items-stretch gap-4">
              <Stat label="请求数" value={data.summary.total_requests.toLocaleString()} />
              <div className="w-px self-stretch bg-line" />
              <Stat label="总 token" value={data.summary.total_tokens.toLocaleString()} />
            </div>

            {Object.keys(data.summary.by_model).length > 0 && (
              <ul className="mt-4 divide-y divide-line border-y border-line">
                {Object.entries(data.summary.by_model).map(([model, stat]) => (
                  <li
                    key={model}
                    className="flex items-center justify-between py-1.5 text-xs"
                  >
                    <span className="font-mono text-fg-muted">{model}</span>
                    <span className="font-mono tabular-nums text-fg-dim">
                      {stat.requests} · {stat.total_tokens.toLocaleString()} tok
                    </span>
                  </li>
                ))}
              </ul>
            )}

            <div className="mt-5 mb-2 text-[10px] uppercase tracking-[0.2em] text-fg-dim">
              最近请求
            </div>
            <ul className="min-h-0 flex-1 divide-y divide-line overflow-y-auto">
              {data.items.length === 0 && (
                <li className="py-3 text-xs text-fg-dim">
                  暂无记录，先发起一次对话。
                </li>
              )}
              {data.items.map((it, i) => (
                <li key={i} className="py-3">
                  <div className="truncate text-sm text-fg" title={it.query}>
                    {it.query}
                  </div>
                  <div className="mt-1.5 flex flex-wrap items-center gap-2 text-[11px] text-fg-dim">
                    <span className="font-mono text-fg-muted">{it.model}</span>
                    {it.forced ? (
                      <span className="rounded-full bg-surface-2 px-2 py-0.5 font-mono text-[10px] ring-1 ring-inset ring-line">
                        forced
                      </span>
                    ) : (
                      <TierBadge tier={it.tier} />
                    )}
                    <span className="font-mono tabular-nums">
                      {it.usage.total_tokens} tok
                    </span>
                    <span className="ml-auto font-mono text-fg-dim/70">
                      {it.ts.replace("T", " ").slice(5, 19)}
                    </span>
                  </div>
                </li>
              ))}
            </ul>
          </>
        )}

        {!data && !error && loading && (
          <p className="text-xs text-fg-dim">加载中…</p>
        )}
      </div>
    </section>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex-1">
      <div className="font-mono text-2xl tabular-nums text-fg">{value}</div>
      <div className="mt-0.5 text-[10px] uppercase tracking-[0.18em] text-fg-dim">
        {label}
      </div>
    </div>
  );
}

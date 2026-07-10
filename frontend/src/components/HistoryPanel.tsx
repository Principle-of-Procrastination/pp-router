import { useCallback, useEffect, useState } from "react";
import { ApiError, getHistory, type HistoryResponse } from "../api";
import { TierBadge } from "./badges";
import { formatUsageTokens } from "./usageText";

export default function HistoryPanel({
  version,
  onUnauthorized,
}: {
  version: number;
  onUnauthorized: () => void;
}) {
  const [data, setData] = useState<HistoryResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await getHistory(50));
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        onUnauthorized();
        return;
      }
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [onUnauthorized]);

  useEffect(() => {
    void load();
  }, [load, version]);

  return (
    <section className="flex min-h-0 flex-col overflow-hidden rounded-2xl bg-surface/70 ring-1 ring-line">
      <header className="flex shrink-0 items-center justify-between border-b border-line px-4 py-2.5 sm:px-5 sm:py-3.5">
        <span className="text-[11px] uppercase tracking-[0.2em] text-fg-dim">
          历史与用量
        </span>
        <button
          onClick={load}
          disabled={loading}
          className="rounded-lg px-2.5 py-1 text-xs text-fg-dim transition-colors hover:bg-surface-2 hover:text-fg-muted"
        >
          {loading ? "刷新中…" : "刷新"}
        </button>
      </header>

      <div className="flex min-h-0 flex-1 flex-col px-4 py-3 sm:px-5 sm:py-4 lg:px-5 lg:py-5">
        {error && <p className="text-xs text-[#e8a89c]">{error}</p>}

        {data && (
          <>
            <div className="shrink-0">
              <div className="flex items-stretch gap-2 sm:gap-4 lg:gap-5">
                <Stat label="请求数" value={data.summary.total_requests.toLocaleString()} />
                <div className="w-px self-stretch bg-line" />
                <Stat label="总 token" value={data.summary.total_tokens.toLocaleString()} />
              </div>

              {Object.keys(data.summary.by_model).length > 0 && (
                <ul className="mt-2 divide-y divide-line border-y border-line sm:mt-4 lg:mt-5">
                  {Object.entries(data.summary.by_model).map(([model, stat]) => (
                    <li
                      key={model}
                      className="flex items-center justify-between gap-2 py-1 text-[11px] sm:py-1.5 sm:text-xs lg:py-2"
                    >
                      <span className="truncate font-mono text-fg-muted">{model}</span>
                      <span className="shrink-0 font-mono tabular-nums text-fg-dim">
                        {stat.requests} · {formatUsageTokens({
                          prompt_tokens: 0,
                          completion_tokens: 0,
                          total_tokens: stat.total_tokens,
                        })}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <div className="mt-2 mb-1.5 shrink-0 text-[10px] uppercase tracking-[0.2em] text-fg-dim sm:mt-4 sm:mb-2 lg:mt-5">
              最近请求
            </div>
            <ul className="min-h-0 flex-1 divide-y divide-line overflow-y-auto overscroll-contain [-webkit-overflow-scrolling:touch]">
              {data.items.length === 0 && (
                <li className="py-2 text-xs text-fg-dim sm:py-3 lg:py-4">
                  暂无记录，先发起一次对话。
                </li>
              )}
              {data.items.map((it, i) => (
                <li key={i} className="py-2 sm:py-3 lg:py-3.5">
                  <div className="truncate text-sm text-fg lg:text-[15px]" title={it.query}>
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
                      {formatUsageTokens(it.usage)}
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
    <div className="min-w-0 flex-1">
      <div className="truncate font-mono text-lg tabular-nums text-fg sm:text-xl lg:text-2xl">
        {value}
      </div>
      <div className="mt-0.5 truncate text-[9px] uppercase tracking-[0.14em] text-fg-dim sm:text-[10px] sm:tracking-[0.18em]">
        {label}
      </div>
    </div>
  );
}

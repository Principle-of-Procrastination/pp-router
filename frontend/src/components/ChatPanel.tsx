import { useState, type KeyboardEvent } from "react";
import {
  streamChat,
  type ModelInfo,
  type RoutingInfo,
  type Usage,
} from "../api";
import { TierBadge } from "./badges";

type AssistantTurn = {
  role: "assistant";
  content: string;
  reasoning: boolean;
  done: boolean;
  model?: string;
  routing?: RoutingInfo;
  usage?: Usage;
};

type Turn = { role: "user"; content: string } | AssistantTurn;

export default function ChatPanel({
  models,
  onChatComplete,
}: {
  models: ModelInfo[];
  onChatComplete: () => void;
}) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [selected, setSelected] = useState("auto");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function patchLast(fn: (a: AssistantTurn) => AssistantTurn) {
    setTurns((cur) => {
      const copy = cur.slice();
      const last = copy[copy.length - 1];
      if (last && last.role === "assistant") copy[copy.length - 1] = fn(last);
      return copy;
    });
  }

  async function send() {
    const text = input.trim();
    if (!text || loading) return;

    const history: Turn[] = [...turns, { role: "user", content: text }];
    setTurns([
      ...history,
      { role: "assistant", content: "", reasoning: false, done: false },
    ]);
    setInput("");
    setLoading(true);
    setError(null);

    try {
      await streamChat(
        {
          messages: history.map((t) => ({ role: t.role, content: t.content })),
          ...(selected !== "auto" ? { model: selected } : {}),
        },
        {
          onRouting: (r) =>
            patchLast((a) => ({ ...a, routing: r, model: r.target_group })),
          onReasoning: () =>
            patchLast((a) => (a.content ? a : { ...a, reasoning: true })),
          onDelta: (t) =>
            patchLast((a) => ({ ...a, content: a.content + t, reasoning: false })),
          onDone: (d) =>
            patchLast((a) => ({ ...a, model: d.model, usage: d.usage, done: true })),
        },
      );
      onChatComplete();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      patchLast((a) => ({ ...a, done: true }));
    } finally {
      setLoading(false);
    }
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void send();
    }
  }

  return (
    <section className="flex min-h-0 flex-col overflow-hidden rounded-2xl bg-surface/70 ring-1 ring-line">
      <header className="flex items-center justify-between gap-3 border-b border-line px-5 py-3.5">
        <span className="text-[11px] uppercase tracking-[0.2em] text-fg-dim">
          对话
        </span>
        <div className="flex items-center gap-2">
          <select
            value={selected}
            onChange={(e) => setSelected(e.target.value)}
            className="rounded-lg border border-line bg-surface-2 px-2.5 py-1.5 font-mono text-[11px] text-fg-muted outline-none transition-colors hover:text-fg focus:border-accent/40"
          >
            <option value="auto">自动路由</option>
            {models.map((m) => (
              <option key={m.id} value={m.id}>
                {m.id}
              </option>
            ))}
          </select>
          <button
            onClick={() => {
              setTurns([]);
              setError(null);
            }}
            className="rounded-lg px-2.5 py-1.5 text-xs text-fg-dim transition-colors hover:bg-surface-2 hover:text-fg-muted"
          >
            清空
          </button>
        </div>
      </header>

      <div className="flex-1 space-y-6 overflow-y-auto px-5 py-6">
        {turns.length === 0 && (
          <div className="mx-auto mt-16 max-w-sm text-center">
            <p className="font-serif text-xl text-fg-muted">
              问一个问题，看它被路由到哪个模型。
            </p>
            <p className="mt-2 text-xs leading-relaxed text-fg-dim">
              选「自动路由」由后端按难度挑模型，或在右上角指定。
              强模型的长推理会逐字流式返回。
            </p>
          </div>
        )}

        {turns.map((t, i) =>
          t.role === "user" ? (
            <div key={i} className="flex justify-end">
              <div className="max-w-[80%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-surface-2 px-4 py-2.5 text-sm leading-relaxed text-fg ring-1 ring-line">
                {t.content}
              </div>
            </div>
          ) : (
            <div key={i} className="flex flex-col gap-2">
              <div className="flex items-center gap-2">
                <span className="h-1.5 w-1.5 rounded-full bg-accent-strong" />
                <span className="text-[10px] uppercase tracking-[0.2em] text-fg-dim">
                  router
                </span>
              </div>
              <div className="whitespace-pre-wrap pl-3.5 text-[15px] leading-7 text-fg/95">
                {t.content ? (
                  <>
                    {t.content}
                    {!t.done && (
                      <span className="ml-0.5 animate-pulse text-accent-strong">
                        ▌
                      </span>
                    )}
                  </>
                ) : (
                  <span className="inline-flex items-center gap-1.5 text-fg-dim">
                    <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-accent-strong" />
                    {t.reasoning ? "推理中…" : "生成中…"}
                  </span>
                )}
              </div>
              {t.done && t.usage && (
                <div className="flex flex-wrap items-center gap-2 pl-3.5 text-[11px] text-fg-dim">
                  <span className="font-mono text-fg-muted">{t.model}</span>
                  {t.routing?.forced ? (
                    <span className="rounded-full bg-surface-2 px-2 py-0.5 font-mono text-[10px] ring-1 ring-inset ring-line">
                      forced
                    </span>
                  ) : (
                    <>
                      <TierBadge tier={t.routing?.tier ?? null} />
                      {t.routing?.score != null && (
                        <span className="font-mono">
                          {t.routing.score.toFixed(2)}
                        </span>
                      )}
                    </>
                  )}
                  <span className="text-line">·</span>
                  <span className="font-mono tabular-nums">
                    {t.usage.total_tokens} tok
                    <span className="text-fg-dim/70">
                      {" "}
                      ({t.usage.prompt_tokens}/{t.usage.completion_tokens})
                    </span>
                  </span>
                </div>
              )}
            </div>
          ),
        )}

        {error && (
          <div className="rounded-xl border border-[#3a2420] bg-[#1f1513] px-4 py-3 text-sm text-[#e8a89c]">
            请求失败：{error}
          </div>
        )}
      </div>

      <div className="border-t border-line p-3.5">
        <div className="flex items-end gap-2.5">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKeyDown}
            rows={2}
            placeholder="输入消息，Enter 发送，Shift+Enter 换行"
            className="flex-1 resize-none rounded-xl border border-line bg-surface-2 px-3.5 py-2.5 text-sm leading-relaxed text-fg outline-none transition-colors placeholder:text-fg-dim focus:border-accent/40"
          />
          <button
            onClick={send}
            disabled={loading || !input.trim()}
            className="rounded-xl bg-accent px-5 py-2.5 text-sm font-medium text-ink transition-colors hover:bg-accent-strong disabled:cursor-not-allowed disabled:bg-surface-2 disabled:text-fg-dim"
          >
            发送
          </button>
        </div>
      </div>
    </section>
  );
}

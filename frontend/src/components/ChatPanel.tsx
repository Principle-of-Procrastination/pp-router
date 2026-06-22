import { useState, type KeyboardEvent } from "react";
import {
  postChat,
  type ChatResponse,
  type ModelInfo,
  type RoutingInfo,
  type Usage,
} from "../api";
import { TierBadge } from "./badges";

type Turn =
  | { role: "user"; content: string }
  | {
      role: "assistant";
      content: string;
      model: string;
      routing: RoutingInfo;
      usage: Usage;
    };

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

  async function send() {
    const text = input.trim();
    if (!text || loading) return;

    const next: Turn[] = [...turns, { role: "user", content: text }];
    setTurns(next);
    setInput("");
    setLoading(true);
    setError(null);

    try {
      const resp: ChatResponse = await postChat({
        messages: next.map((t) => ({ role: t.role, content: t.content })),
        ...(selected !== "auto" ? { model: selected } : {}),
      });
      setTurns((cur) => [
        ...cur,
        {
          role: "assistant",
          content: resp.content,
          model: resp.model,
          routing: resp.routing,
          usage: resp.usage,
        },
      ]);
      onChatComplete();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
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
    <section className="flex min-h-0 flex-col rounded-xl border border-slate-800 bg-slate-900/50">
      <header className="flex items-center justify-between gap-3 border-b border-slate-800 px-4 py-3">
        <h2 className="text-sm font-semibold text-slate-200">对话</h2>
        <div className="flex items-center gap-2">
          <label className="text-xs text-slate-400">模型</label>
          <select
            value={selected}
            onChange={(e) => setSelected(e.target.value)}
            className="rounded-md border border-slate-700 bg-slate-800 px-2 py-1 text-xs text-slate-100 outline-none focus:border-sky-500"
          >
            <option value="auto">自动路由（按难度）</option>
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
            className="rounded-md border border-slate-700 px-2 py-1 text-xs text-slate-300 hover:bg-slate-800"
          >
            清空
          </button>
        </div>
      </header>

      <div className="flex-1 space-y-4 overflow-y-auto px-4 py-4">
        {turns.length === 0 && (
          <p className="mt-10 text-center text-sm text-slate-500">
            输入一个问题开始对话。选「自动路由」由后端按难度选模型，或指定具体模型。
          </p>
        )}
        {turns.map((t, i) =>
          t.role === "user" ? (
            <div key={i} className="flex justify-end">
              <div className="max-w-[80%] whitespace-pre-wrap rounded-2xl rounded-br-sm bg-sky-600 px-3.5 py-2 text-sm text-white">
                {t.content}
              </div>
            </div>
          ) : (
            <div key={i} className="flex flex-col items-start gap-1">
              <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-bl-sm bg-slate-800 px-3.5 py-2 text-sm text-slate-100">
                {t.content}
              </div>
              <div className="flex flex-wrap items-center gap-1.5 pl-1 text-[11px] text-slate-400">
                <span className="font-mono text-slate-300">{t.model}</span>
                {t.routing.forced ? (
                  <span className="rounded bg-slate-700 px-1.5 py-0.5">forced</span>
                ) : (
                  <>
                    <TierBadge tier={t.routing.tier} />
                    {t.routing.score !== null && (
                      <span>score {t.routing.score.toFixed(2)}</span>
                    )}
                  </>
                )}
                <span className="text-slate-500">·</span>
                <span>
                  {t.usage.total_tokens} tok（in {t.usage.prompt_tokens} / out{" "}
                  {t.usage.completion_tokens}）
                </span>
              </div>
            </div>
          ),
        )}
        {loading && <p className="text-sm text-slate-500">思考中…</p>}
        {error && <p className="text-sm text-rose-400">请求失败：{error}</p>}
      </div>

      <div className="border-t border-slate-800 p-3">
        <div className="flex items-end gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKeyDown}
            rows={2}
            placeholder="输入消息，Enter 发送，Shift+Enter 换行"
            className="flex-1 resize-none rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-100 outline-none placeholder:text-slate-500 focus:border-sky-500"
          />
          <button
            onClick={send}
            disabled={loading || !input.trim()}
            className="rounded-lg bg-sky-600 px-4 py-2 text-sm font-medium text-white hover:bg-sky-500 disabled:cursor-not-allowed disabled:opacity-50"
          >
            发送
          </button>
        </div>
      </div>
    </section>
  );
}

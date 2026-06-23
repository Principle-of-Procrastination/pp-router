export interface ModelInfo {
  id: string;
  litellm_model: string;
  tiers: string[];
}

export interface Usage {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
}

export interface RoutingInfo {
  target_group: string;
  forced: boolean;
  tier: string | null;
  score: number | null;
}

export interface ChatResponse {
  content: string;
  model: string;
  routing: RoutingInfo;
  usage: Usage;
}

export type Role = "system" | "user" | "assistant";

export interface ChatMessage {
  role: Role;
  content: string;
}

export interface ChatRequestBody {
  messages: ChatMessage[];
  model?: string;
}

export interface HistoryItem {
  ts: string;
  query: string;
  model: string;
  tier: string | null;
  forced: boolean;
  score: number | null;
  usage: Usage;
}

export interface ModelStat {
  requests: number;
  total_tokens: number;
}

export interface HistoryResponse {
  summary: {
    total_requests: number;
    total_tokens: number;
    by_model: Record<string, ModelStat>;
  };
  items: HistoryItem[];
}

// dev：留空走 Vite 代理 /api → :4000；prod：构建时注入 VITE_API_BASE=<后端URL>
const BASE = import.meta.env.VITE_API_BASE ?? "/api";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(BASE + path, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`HTTP ${res.status}: ${text.slice(0, 300)}`);
  }
  return (await res.json()) as T;
}

export function getModels(): Promise<ModelInfo[]> {
  return req<ModelInfo[]>("/models");
}

export function postChat(body: ChatRequestBody): Promise<ChatResponse> {
  return req<ChatResponse>("/chat", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function getHistory(limit = 50): Promise<HistoryResponse> {
  return req<HistoryResponse>(`/history?limit=${limit}`);
}

export interface StreamHandlers {
  onRouting?: (routing: RoutingInfo) => void;
  onDelta: (text: string) => void;
  onReasoning?: () => void;
  onDone: (d: { model: string; usage: Usage }) => void;
}

export async function streamChat(
  body: ChatRequestBody,
  handlers: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(BASE + "/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok || !res.body) {
    const text = await res.text().catch(() => "");
    throw new Error(`HTTP ${res.status}: ${text.slice(0, 300)}`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });

    let sep: number;
    while ((sep = buf.indexOf("\n\n")) !== -1) {
      const block = buf.slice(0, sep);
      buf = buf.slice(sep + 2);
      const dataLine = block
        .split("\n")
        .find((l) => l.startsWith("data:"));
      if (!dataLine) continue; // 心跳注释行 ": ping" 等忽略
      const payload = dataLine.slice(5).trim();
      if (!payload) continue;

      const evt = JSON.parse(payload) as {
        type: string;
        content?: string;
        routing?: RoutingInfo;
        model?: string;
        usage?: Usage;
        detail?: string;
      };
      if (evt.type === "routing" && evt.routing) handlers.onRouting?.(evt.routing);
      else if (evt.type === "delta" && evt.content) handlers.onDelta(evt.content);
      else if (evt.type === "reasoning") handlers.onReasoning?.();
      else if (evt.type === "done")
        handlers.onDone({
          model: evt.model ?? body.model ?? "",
          usage: evt.usage ?? {
            prompt_tokens: 0,
            completion_tokens: 0,
            total_tokens: 0,
          },
        });
      else if (evt.type === "error") throw new Error(evt.detail ?? "upstream error");
    }
  }
}

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

const BASE = "/api";

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

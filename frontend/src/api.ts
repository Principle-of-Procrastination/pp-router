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

interface SessionResponse {
  token: string;
  expires_at: number;
}

type StoredSession = SessionResponse;

const BASE = import.meta.env.VITE_API_BASE ?? "/api";
const SESSION_KEY = "pprouter.session";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export function hasSession(): boolean {
  return getSession() !== null;
}

export function clearSession(): void {
  sessionStorage.removeItem(SESSION_KEY);
}

export async function login(accessKey: string): Promise<void> {
  const res = await fetch(BASE + "/session", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ access_key: accessKey }),
  });
  if (!res.ok) throw await toApiError(res);
  const session = (await res.json()) as SessionResponse;
  sessionStorage.setItem(SESSION_KEY, JSON.stringify(session));
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = authenticatedHeaders(init?.headers);
  const res = await fetch(BASE + path, { ...init, headers });
  if (!res.ok) throw await toApiError(res);
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

interface StreamEvent {
  type: string;
  content?: string;
  routing?: RoutingInfo;
  model?: string;
  usage?: Usage;
  detail?: string;
}

export async function streamChat(
  body: ChatRequestBody,
  handlers: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(BASE + "/chat/stream", {
    method: "POST",
    headers: authenticatedHeaders(),
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok || !res.body) throw await toApiError(res);

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  let receivedDone = false;

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });

      let sep: number;
      while ((sep = buf.indexOf("\n\n")) !== -1) {
        const block = buf.slice(0, sep);
        buf = buf.slice(sep + 2);
        const dataLine = block.split("\n").find((line) => line.startsWith("data:"));
        if (!dataLine) continue;
        const payload = dataLine.slice(5).trim();
        if (!payload) continue;

        const event = parseStreamEvent(payload);
        if (event.type === "routing" && event.routing) {
          handlers.onRouting?.(event.routing);
        } else if (event.type === "delta" && event.content) {
          handlers.onDelta(event.content);
        } else if (event.type === "reasoning") {
          handlers.onReasoning?.();
        } else if (event.type === "done") {
          receivedDone = true;
          handlers.onDone({
            model: event.model ?? body.model ?? "",
            usage: event.usage ?? emptyUsage(),
          });
        } else if (event.type === "error") {
          throw new Error(event.detail ?? "upstream request failed");
        }
      }
    }
  } finally {
    reader.releaseLock();
  }

  if (!receivedDone && !signal?.aborted) {
    throw new Error("stream ended before completion");
  }
}

function authenticatedHeaders(existing?: HeadersInit): Headers {
  const session = getSession();
  if (!session) throw new ApiError(401, "session expired");
  const headers = new Headers(existing);
  headers.set("Content-Type", "application/json");
  headers.set("Authorization", `Bearer ${session.token}`);
  return headers;
}

function getSession(): StoredSession | null {
  const raw = sessionStorage.getItem(SESSION_KEY);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as unknown;
    if (!isStoredSession(parsed) || parsed.expires_at <= Math.floor(Date.now() / 1000)) {
      clearSession();
      return null;
    }
    return parsed;
  } catch {
    clearSession();
    return null;
  }
}

function isStoredSession(value: unknown): value is StoredSession {
  if (!value || typeof value !== "object") return false;
  return (
    "token" in value &&
    typeof value.token === "string" &&
    "expires_at" in value &&
    typeof value.expires_at === "number"
  );
}

function parseStreamEvent(payload: string): StreamEvent {
  const value = JSON.parse(payload) as unknown;
  if (!value || typeof value !== "object" || !("type" in value)) {
    throw new Error("invalid stream event");
  }
  const event = value as Record<string, unknown>;
  if (typeof event.type !== "string") throw new Error("invalid stream event type");
  return {
    type: event.type,
    content: typeof event.content === "string" ? event.content : undefined,
    detail: typeof event.detail === "string" ? event.detail : undefined,
    model: typeof event.model === "string" ? event.model : undefined,
    routing: isRoutingInfo(event.routing) ? event.routing : undefined,
    usage: isUsage(event.usage) ? event.usage : undefined,
  };
}

function isRoutingInfo(value: unknown): value is RoutingInfo {
  if (!value || typeof value !== "object") return false;
  const routing = value as Record<string, unknown>;
  return (
    typeof routing.target_group === "string" &&
    typeof routing.forced === "boolean" &&
    (typeof routing.tier === "string" || routing.tier === null) &&
    (typeof routing.score === "number" || routing.score === null)
  );
}

function isUsage(value: unknown): value is Usage {
  if (!value || typeof value !== "object") return false;
  const usage = value as Record<string, unknown>;
  return (
    typeof usage.prompt_tokens === "number" &&
    typeof usage.completion_tokens === "number" &&
    typeof usage.total_tokens === "number"
  );
}

async function toApiError(res: Response): Promise<ApiError> {
  const text = await res.text().catch(() => "");
  let message = text.slice(0, 300) || `HTTP ${res.status}`;
  try {
    const payload = JSON.parse(text) as unknown;
    if (payload && typeof payload === "object" && "detail" in payload) {
      const detail = payload.detail;
      message = typeof detail === "string" ? detail : JSON.stringify(detail);
    }
  } catch {
    // Keep the bounded plain-text response.
  }
  return new ApiError(res.status, message);
}

function emptyUsage(): Usage {
  return { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0 };
}

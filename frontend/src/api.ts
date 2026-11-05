let csrf = "";
export function setCSRF(value: string) {
  csrf = value;
}
export async function api<T = any>(
  path: string,
  method = "GET",
  body?: unknown,
): Promise<T> {
  const response = await fetch("/api/admin/v1" + path, {
    method,
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok)
    throw new Error(data.error?.message || `HTTP ${response.status}`);
  return data;
}

export async function readSSE(
  response: Response,
  onChunk: (data: any) => void,
) {
  if (!response.ok) {
    const body = await response.json();
    throw new Error(body.error?.message || "调用失败");
  }
  const reader = response.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "",
    doneSeen = false;
  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done }).replace(/\r\n/g, "\n");
      let end: number;
      while ((end = buffer.indexOf("\n\n")) >= 0) {
        const frame = buffer.slice(0, end);
        buffer = buffer.slice(end + 2);
        const data = frame
          .split("\n")
          .filter((line) => line.startsWith("data:"))
          .map((line) => line.slice(5).trim())
          .join("\n");
        if (!data) continue;
        if (data === "[DONE]") {
          doneSeen = true;
          continue;
        }
        const parsed = JSON.parse(data);
        if (parsed.error) throw new Error(parsed.error.message);
        onChunk(parsed);
      }
      if (done) break;
    }
    if (!doneSeen) throw new Error("响应中断，完整用量请查看调用记录。");
  } finally {
    reader.releaseLock();
  }
}

export async function debugCall(
  keyId: string,
  request: unknown,
  signal: AbortSignal,
  onChunk: (data: any) => void,
) {
  const response = await fetch("/api/admin/v1/playground", {
    method: "POST",
    signal,
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
    credentials: "same-origin",
    body: JSON.stringify({ key_id: keyId, request }),
  });
  await readSSE(response, onChunk);
}

export function formatNumber(value: number | null | undefined) {
  return value == null ? "—" : value.toLocaleString("zh-CN");
}

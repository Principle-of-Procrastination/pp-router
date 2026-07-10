import { beforeEach, describe, expect, it, vi } from "vitest";

import { clearSession, login, streamChat } from "./api";


class MemoryStorage implements Storage {
  private readonly values = new Map<string, string>();

  get length(): number {
    return this.values.size;
  }

  clear(): void {
    this.values.clear();
  }

  getItem(key: string): string | null {
    return this.values.get(key) ?? null;
  }

  key(index: number): string | null {
    return [...this.values.keys()][index] ?? null;
  }

  removeItem(key: string): void {
    this.values.delete(key);
  }

  setItem(key: string, value: string): void {
    this.values.set(key, value);
  }
}


function streamResponse(events: string): Response {
  const encoder = new TextEncoder();
  return new Response(
    new ReadableStream({
      start(controller) {
        controller.enqueue(encoder.encode(events));
        controller.close();
      },
    }),
    { status: 200 },
  );
}


async function authenticate(fetchMock: ReturnType<typeof vi.fn>): Promise<void> {
  fetchMock.mockResolvedValueOnce(
    new Response(JSON.stringify({ token: "session-token", expires_at: 4_102_444_800 }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }),
  );
  await login("access-key");
}


describe("streamChat", () => {
  beforeEach(() => {
    vi.stubGlobal("sessionStorage", new MemoryStorage());
    clearSession();
  });

  it("sends the session and requires a done event", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    await authenticate(fetchMock);
    fetchMock.mockResolvedValueOnce(
      streamResponse(
        'data: {"type":"delta","content":"ok"}\n\n' +
          'data: {"type":"done","model":"glm-4.7","usage":{"prompt_tokens":1,"completion_tokens":1,"total_tokens":2}}\n\n',
      ),
    );
    const pieces: string[] = [];

    await streamChat(
      { messages: [{ role: "user", content: "hi" }] },
      { onDelta: (text) => pieces.push(text), onDone: () => undefined },
    );

    expect(pieces).toEqual(["ok"]);
    const headers = new Headers(fetchMock.mock.calls[1][1].headers);
    expect(headers.get("Authorization")).toBe("Bearer session-token");
  });

  it("rejects a truncated stream", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    await authenticate(fetchMock);
    fetchMock.mockResolvedValueOnce(
      streamResponse('data: {"type":"delta","content":"partial"}\n\n'),
    );

    await expect(
      streamChat(
        { messages: [{ role: "user", content: "hi" }] },
        { onDelta: () => undefined, onDone: () => undefined },
      ),
    ).rejects.toThrow("stream ended before completion");
  });
});

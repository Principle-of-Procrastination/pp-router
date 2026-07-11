import { describe, expect, it, vi } from "vitest";

import { streamChat } from "./api";


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


describe("streamChat", () => {
  it("uses the public API and requires a done event", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
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
    const headers = new Headers(fetchMock.mock.calls[0][1].headers);
    expect(headers.get("Authorization")).toBeNull();
    expect(headers.get("Content-Type")).toBe("application/json");
  });

  it("rejects a truncated stream", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
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

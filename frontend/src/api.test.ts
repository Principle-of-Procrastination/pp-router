import { describe, expect, it } from "vitest";
import { formatNumber, readSSE } from "./api";

function stream(parts: string[]) {
  return new Response(
    new ReadableStream({
      start(c) {
        for (const p of parts) c.enqueue(new TextEncoder().encode(p));
        c.close();
      },
    }),
  );
}
describe("OpenAI stream consumption", () => {
  it("handles split frames, heartbeats and final usage", async () => {
    const chunks: any[] = [];
    await readSSE(
      stream([
        ': heartbeat\n\ndata: {"choices":[',
        '{"delta":{"content":"你好"}}]}\n',
        '\ndata: {"choices":[],"usage":{"total_tokens":3}}\n\ndata: [DONE]\n\n',
      ]),
      (c) => chunks.push(c),
    );
    expect(chunks[0].choices[0].delta.content).toBe("你好");
    expect(chunks[1].usage.total_tokens).toBe(3);
  });
  it("does not treat premature EOF as success", async () => {
    await expect(
      readSSE(stream(['data: {"choices":[]}\n\n']), () => {}),
    ).rejects.toThrow("响应中断");
  });
  it("shows structured stream errors", async () => {
    await expect(
      readSSE(
        stream(['data: {"error":{"message":"upstream timeout"}}\n\n']),
        () => {},
      ),
    ).rejects.toThrow("upstream timeout");
  });
  it("distinguishes unknown usage from a known zero", () => {
    expect(formatNumber(null)).toBe("—");
    expect(formatNumber(0)).toBe("0");
  });
});

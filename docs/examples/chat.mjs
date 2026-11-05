// Server-side example. One explicit model call; no retry loop.
const baseURL = process.env.PP_ROUTER_BASE_URL?.replace(/\/+$/, '');
const apiKey = process.env.PP_ROUTER_API_KEY;
if (!baseURL?.endsWith('/v1') || !apiKey) {
  throw new Error('Set PP_ROUTER_BASE_URL (ending in /v1) and PP_ROUTER_API_KEY');
}

const response = await fetch(`${baseURL}/chat/completions`, {
  method: 'POST',
  headers: {
    Authorization: `Bearer ${apiKey}`,
    'Content-Type': 'application/json',
    'X-Trace-ID': `suite-example-${crypto.randomUUID()}`,
  },
  body: JSON.stringify({
    model: 'deepseek-flash',
    messages: [{ role: 'user', content: '只回复 OK。' }],
    max_tokens: 32,
  }),
  signal: AbortSignal.timeout(210_000),
});
const requestId = response.headers.get('x-request-id');
const contentType = response.headers.get('content-type') ?? '';
if (!contentType.includes('application/json')) {
  throw new Error(`Unexpected response: HTTP ${response.status}; check the gateway URL`);
}
const body = await response.json();
if (!response.ok || body.error) {
  throw new Error(`HTTP ${response.status}; code=${body.error?.code}; request_id=${requestId}`);
}
console.log('request_id:', requestId);
console.log('model:', body.model);
console.log('answer:', body.choices[0].message.content);
console.log('finish_reason:', body.choices[0].finish_reason);
console.log('usage:', body.usage ?? 'unknown; check request details');

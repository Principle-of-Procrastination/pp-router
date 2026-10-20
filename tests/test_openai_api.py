import asyncio
import hashlib
import json
from dataclasses import replace

import httpx
import pytest
from fastapi import FastAPI
from starlette.requests import ClientDisconnect

from pprouter import api, openai_api
from pprouter.config import Settings
from pprouter.openai_schemas import MAX_REQUEST_BYTES
from pprouter.schemas import HistorySummary, RoutingInfo
from pprouter.security import ConcurrencyGate, SlidingWindowRateLimiter


TOKEN = "test-only-key-0123456789-abcdef0123456789"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
MESSAGES = [{"role": "user", "content": "Implement a parser"}]
TOOL_CALL = {
    "id": "call_read",
    "type": "function",
    "function": {"name": "read_file", "arguments": '{"path":"main.py"}'},
}
TOOLS = [{
    "type": "function",
    "function": {
        "name": "read_file",
        "description": "Read a workspace file",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
    },
}]


def _completion():
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 1,
        "model": "glm-5.1",
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": None, "tool_calls": [TOOL_CALL]},
            "finish_reason": "tool_calls",
        }],
        "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
        "_hidden_params": {"api_key": "provider-secret"},
    }


def _chunks():
    base = {"id": "chatcmpl-test", "object": "chat.completion.chunk", "created": 1, "model": "glm-5.1"}
    return [
        {**base, "choices": [{"index": 0, "delta": {"role": "assistant", "content": None,
            "tool_calls": [{"index": 0, "id": "call_read", "type": "function",
                "function": {"name": "read_file", "arguments": '{"path":'}}]}, "finish_reason": None}]},
        {**base, "choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0,
            "function": {"arguments": '"main.py"}'}}]}, "finish_reason": None}]},
        {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
        {**base, "choices": [], "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}},
    ]


class StubStream:
    def __init__(self, *, delay=0, fail=False, chunks=None, close_delay=0):
        self.chunks = iter(_chunks() if chunks is None else chunks)
        self.delay = delay
        self.fail = fail
        self.closed = 0
        self.cancelled = False
        self.close_delay = close_delay
        self.close_started = asyncio.Event()

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            if self.fail:
                raise RuntimeError("provider-secret and private tool output")
            item = next(self.chunks, None)
            if item is None:
                raise StopAsyncIteration
            return item
        except asyncio.CancelledError:
            self.cancelled = True
            raise

    async def aclose(self):
        self.close_started.set()
        await asyncio.sleep(self.close_delay)
        self.closed += 1


class StubEngine:
    def __init__(self, *, stream=None, delay=0, fail=False):
        self.calls = []
        self.stream = stream or StubStream()
        self.delay = delay
        self.fail = fail
        self.cancelled = False

    async def acompletion(self, **kwargs):
        self.calls.append(kwargs)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            if self.fail:
                raise RuntimeError("provider-secret and private tool output")
            return self.stream if kwargs["stream"] else _completion()
        except asyncio.CancelledError:
            self.cancelled = True
            raise


class StubDifficulty:
    def __init__(self):
        self.calls = []

    def route(self, messages):
        self.calls.append(messages)
        return RoutingInfo(target_group="glm-5.1", tier="COMPLEX", score=0.9)


class StubHistory:
    def __init__(self):
        self.items = []

    def append(self, item):
        self.items.append(item)

    def recent(self, limit):
        return self.items[:limit]

    def summary(self):
        return HistorySummary(total_requests=len(self.items), total_tokens=18, by_model={})


def _app(engine=None, **settings_overrides):
    app = FastAPI()
    settings = Settings(
        cors_origins=("http://localhost:5173",),
        chat_requests_per_minute=30,
        global_chat_requests_per_minute=120,
        read_requests_per_minute=120,
        max_concurrent_requests=1,
        upstream_timeout_seconds=1,
        stream_heartbeat_seconds=0.01,
        max_output_tokens=1024,
        history_path="unused.db",
        cloudbase_env_id=None,
        cloudbase_api_key=None,
        cloudbase_history_collection="unused",
        openai_api_key_hash=hashlib.sha256(TOKEN.encode()).digest(),
    )
    app.state.settings = replace(settings, **settings_overrides)
    app.state.router = engine or StubEngine()
    app.state.difficulty = StubDifficulty()
    app.state.history = StubHistory()
    app.state.rate_limiter = SlidingWindowRateLimiter()
    app.state.concurrency = ConcurrencyGate(app.state.settings.max_concurrent_requests)
    app.include_router(api.router)
    app.include_router(openai_api.router)
    return app


async def _post(app, *, headers=None, **body):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        return await client.post("/v1/chat/completions", headers=HEADERS if headers is None else headers,
                                 json={"model": "auto", "messages": MESSAGES, **body})


def test_auto_uses_original_difficulty_and_records_usage_without_prompt_or_tools():
    app = _app()
    response = asyncio.run(_post(app))
    assert response.status_code == 200
    assert app.state.difficulty.calls == [MESSAGES]
    assert app.state.router.calls[0]["model"] == "glm-5.1"
    assert response.json()["choices"][0]["message"]["tool_calls"] == [TOOL_CALL]
    assert response.json()["choices"][0]["message"]["content"] is None
    assert "provider-secret" not in response.text
    recorded = app.state.history.items[0]
    assert recorded.query == ""
    assert recorded.tier == "COMPLEX"
    assert recorded.usage.total_tokens == 18


def test_native_message_and_tool_options_survive_round_trip():
    messages = [
        {"role": "developer", "content": "Follow project rules"},
        {"role": "system", "content": [{"type": "text", "text": "Be concise"}]},
        *MESSAGES,
        {"role": "assistant", "content": "", "reasoning_content": "I should inspect main.py",
         "tool_calls": [TOOL_CALL]},
        {"role": "tool", "tool_call_id": "call_read", "content": "private file contents"},
    ]
    app = _app()
    response = asyncio.run(_post(app, model="glm-4.7", messages=messages, tools=TOOLS,
                                tool_choice={"type": "function", "function": {"name": "read_file"}},
                                parallel_tool_calls=True, max_tokens=5000, temperature=0.3))
    assert response.status_code == 200
    assert app.state.difficulty.calls == []
    call = app.state.router.calls[0]
    assert call["messages"] == messages
    assert call["tools"] == TOOLS
    assert call["tool_choice"] == {"type": "function", "function": {"name": "read_file"}}
    assert call["parallel_tool_calls"] is True
    assert call["model"] == "glm-4.7"
    assert call["max_tokens"] == 1024
    assert app.state.history.items[0].forced
    assert app.state.history.items[0].query == ""


def test_actual_litellm_response_serialization_preserves_tool_calls():
    from litellm import ModelResponse

    response = ModelResponse(**_completion())
    payload = openai_api._payload(response, streaming=False)
    assert payload["choices"][0]["message"]["tool_calls"][0]["function"] == TOOL_CALL["function"]
    assert payload["choices"][0]["finish_reason"] == "tool_calls"
    assert openai_api._usage(payload).total_tokens == 18
    assert "_hidden_params" not in payload


def test_auto_classification_uses_developer_and_user_text_but_not_tool_results():
    messages = [{"role": "developer", "content": [{"type": "text", "text": "Rules"}]},
                *MESSAGES, {"role": "tool", "tool_call_id": "call_read", "content": "private"}]
    app = _app()
    response = asyncio.run(_post(app, messages=messages))
    assert response.status_code == 200
    assert app.state.difficulty.calls == [[{"role": "system", "content": "Rules"}, *MESSAGES]]
    assert app.state.router.calls[0]["messages"] == messages


@pytest.mark.parametrize("token_field", ["max_tokens", "max_completion_tokens"])
def test_client_can_request_a_lower_token_cap(token_field):
    app = _app()
    assert asyncio.run(_post(app, **{token_field: 128})).status_code == 200
    assert app.state.router.calls[0]["max_tokens"] == 128
    assert "max_completion_tokens" not in app.state.router.calls[0]


def test_sdk_structured_output_and_standard_options_pass_through():
    app = _app()
    response_format = {"type": "json_schema", "json_schema": {
        "name": "answer", "schema": {"type": "object", "properties": {"answer": {"type": "string"}}},
        "strict": True,
    }}
    options = {"response_format": response_format, "user": "opaque-user-id", "seed": 9,
               "top_p": 0.8, "frequency_penalty": 0.2, "presence_penalty": 0.3, "stop": ["STOP"]}
    assert asyncio.run(_post(app, **options)).status_code == 200
    call = app.state.router.calls[0]
    assert {name: call[name] for name in options} == options


@pytest.mark.parametrize("tools", [[], [{
    "type": "function", "function": {**TOOLS[0]["function"], "strict": False},
}]])
def test_native_opencode_payload_accepts_store_false_without_forwarding_it(tools):
    app = _app()
    response = asyncio.run(_post(
        app, stream=True, store=False, stream_options={"include_usage": True},
        max_completion_tokens=512, tools=tools, tool_choice="auto",
    ))
    assert response.status_code == 200
    assert response.text.endswith("data: [DONE]\n\n")
    call = app.state.router.calls[0]
    assert "store" not in call
    assert call["tools"] == tools
    assert call["tool_choice"] == "auto"
    assert call["max_tokens"] == 512


def test_models_requires_same_bearer_and_exposes_only_public_aliases():
    async def exercise():
        app = _app()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            assert (await client.get("/v1/models")).status_code == 401
            response = await client.get("/v1/models", headers=HEADERS)
            assert response.status_code == 200
            assert [item["id"] for item in response.json()["data"]] == [
                "auto", "step-3.7-flash", "glm-4.7", "glm-5.1"]
            assert "api_base" not in response.text
            assert (await client.get("/models")).status_code == 200
    asyncio.run(exercise())


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Basic nope"}, {"Authorization": "Bearer bad"}])
def test_auth_fails_before_provider_or_classifier(headers):
    app = _app()
    response = asyncio.run(_post(app, headers=headers))
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert not app.state.router.calls
    assert not app.state.difficulty.calls


def test_compatibility_is_disabled_without_server_key():
    app = _app(openai_api_key_hash=None)
    response = asyncio.run(_post(app))
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "openai_api_disabled"
    assert not app.state.router.calls


@pytest.mark.parametrize("body", [
    {"model": "openai/unconfigured"},
    {"api_base": "https://attacker.example"},
    {"api_key": "supplied-secret"},
    {"messages": [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "secret"}}]}]},
    {"messages": [{"role": "user", "content": "hi"}, {"role": "tool", "content": "orphan"}]},
    {"messages": [{"role": "user", "content": "hi", "tool_calls": [TOOL_CALL]}]},
    {"n": 2},
    {"max_tokens": 0},
    {"max_tokens": 1, "max_completion_tokens": 2},
    {"tool_choice": "required"},
    {"stream_options": {"include_usage": True}},
    {"store": True},
    {"store": 0},
])
def test_rejected_requests_do_not_consume_concurrency_or_leak_input(body):
    async def exercise():
        app = _app()
        response = await _post(app, **body)
        assert response.status_code == 400
        assert "supplied-secret" not in response.text
        assert not app.state.router.calls
        assert await app.state.concurrency.acquire(timeout=0.01)
        app.state.concurrency.release()
    asyncio.run(exercise())


def test_body_size_limit_is_enforced_without_content_length():
    async def exercise():
        app = _app()
        async def body():
            yield b'{"model":"auto","messages":[],"extra":"'
            yield b"x" * MAX_REQUEST_BYTES
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/v1/chat/completions", content=body(),
                headers={**HEADERS, "Content-Type": "application/json"})
        assert response.status_code == 413
        assert not app.state.router.calls
    asyncio.run(exercise())


@pytest.mark.parametrize("include_usage", [True, False])
def test_tool_only_sse_preserves_fragments_and_done_and_closes(include_usage):
    async def exercise():
        app = _app()
        response = await _post(app, stream=True, stream_options={"include_usage": include_usage})
        assert response.status_code == 200
        frames = [line[6:] for line in response.text.splitlines() if line.startswith("data: ")]
        assert frames[-1] == "[DONE]"
        chunks = [json.loads(frame) for frame in frames[:-1]]
        expected = _chunks() if include_usage else _chunks()[:-1]
        assert chunks == expected
        assert app.state.router.stream.closed == 1
        assert app.state.history.items[0].usage.total_tokens == 18
        assert app.state.history.items[0].query == ""
        assert await app.state.concurrency.acquire(timeout=0.01)
        app.state.concurrency.release()
    asyncio.run(exercise())


@pytest.mark.parametrize("streaming", [True, False])
def test_initial_provider_timeout_cancels_request_and_releases_gate(streaming):
    async def exercise():
        engine = StubEngine(delay=1)
        app = _app(engine, upstream_timeout_seconds=0.01)
        response = await _post(app, stream=streaming)
        assert response.status_code == 504
        assert engine.cancelled
        assert await app.state.concurrency.acquire(timeout=0.01)
        app.state.concurrency.release()
    asyncio.run(exercise())


def test_stream_timeout_cancels_read_closes_stream_and_releases_gate():
    async def exercise():
        stream = StubStream(delay=1)
        app = _app(StubEngine(stream=stream), upstream_timeout_seconds=0.03)
        response = await _post(app, stream=True)
        assert "upstream_timeout" in response.text
        assert response.text.endswith("data: [DONE]\n\n")
        assert stream.closed == 1
        assert stream.cancelled
        assert await app.state.concurrency.acquire(timeout=0.01)
        app.state.concurrency.release()
    asyncio.run(exercise())


@pytest.mark.parametrize("streaming", [True, False])
def test_upstream_errors_never_include_provider_details(streaming):
    async def exercise():
        engine = StubEngine(stream=StubStream(fail=True)) if streaming else StubEngine(fail=True)
        app = _app(engine)
        response = await _post(app, stream=streaming)
        assert "upstream_error" in response.text
        assert "provider-secret" not in response.text
        assert "private tool output" not in response.text
        assert await app.state.concurrency.acquire(timeout=0.01)
        app.state.concurrency.release()
        if streaming:
            assert engine.stream.closed == 1
    asyncio.run(exercise())


def test_invalid_stream_chunk_closes_pending_iterator():
    async def exercise():
        stream = StubStream(chunks=[{"error": {"message": "provider-secret"}}])
        app = _app(StubEngine(stream=stream))
        response = await _post(app, stream=True)
        assert "upstream_error" in response.text
        assert "provider-secret" not in response.text
        assert stream.closed == 1
    asyncio.run(exercise())


def test_chat_rate_and_concurrency_limits_apply_to_compatibility_endpoint():
    async def exercise():
        app = _app(chat_requests_per_minute=1)
        assert (await _post(app)).status_code == 200
        assert (await _post(app)).status_code == 429
        assert len(app.state.router.calls) == 1
        busy = _app()
        assert await busy.state.concurrency.acquire()
        response = await _post(busy)
        assert response.status_code == 429
        assert not busy.state.router.calls
        busy.state.concurrency.release()
    asyncio.run(exercise())


def test_disconnected_client_cancels_initial_provider_call():
    async def exercise():
        engine = StubEngine(delay=2)
        app = _app(engine)
        body = json.dumps({"model": "auto", "messages": MESSAGES}).encode()
        sent_body = False
        async def receive():
            nonlocal sent_body
            if not sent_body:
                sent_body = True
                return {"type": "http.request", "body": body, "more_body": False}
            return {"type": "http.disconnect"}
        async def send(message):
            pass
        scope = {"type": "http", "method": "POST", "path": "/v1/chat/completions", "query_string": b"",
                 "headers": [(b"authorization", f"Bearer {TOKEN}".encode()), (b"content-type", b"application/json")],
                 "client": ("127.0.0.1", 1), "server": ("test", 80), "scheme": "http"}
        await app(scope, receive, send)
        assert engine.cancelled
        assert await app.state.concurrency.acquire(timeout=0.01)
        app.state.concurrency.release()
    asyncio.run(exercise())


@pytest.mark.parametrize("disconnect_on", ["http.response.start", "http.response.body"])
def test_asgi_send_disconnect_closes_stream_even_before_body_starts(disconnect_on):
    async def exercise():
        app = _app()
        body = json.dumps({"model": "auto", "messages": MESSAGES, "stream": True}).encode()
        sent_body = False

        async def receive():
            nonlocal sent_body
            if not sent_body:
                sent_body = True
                return {"type": "http.request", "body": body, "more_body": False}
            await asyncio.Event().wait()

        async def send(message):
            if message["type"] == disconnect_on:
                raise OSError("client connection closed")

        scope = {
            "type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"},
            "method": "POST", "path": "/v1/chat/completions", "query_string": b"",
            "headers": [(b"authorization", f"Bearer {TOKEN}".encode()),
                        (b"content-type", b"application/json")],
            "client": ("127.0.0.1", 1), "server": ("test", 80), "scheme": "http",
        }
        with pytest.raises((ClientDisconnect, OSError)):
            await app(scope, receive, send)
        assert app.state.router.stream.closed == 1
        assert await app.state.concurrency.acquire(timeout=0.01)
        app.state.concurrency.release()

    asyncio.run(exercise())


@pytest.mark.parametrize("cancel_task", [False, True])
def test_asgi23_disconnect_or_task_cancellation_waits_for_async_stream_cleanup(cancel_task):
    async def exercise():
        stream = StubStream(close_delay=0.02)
        app = _app(StubEngine(stream=stream))
        body = json.dumps({"model": "auto", "messages": MESSAGES, "stream": True}).encode()
        sent_body = False
        response_started = asyncio.Event()

        async def receive():
            nonlocal sent_body
            if not sent_body:
                sent_body = True
                return {"type": "http.request", "body": body, "more_body": False}
            await response_started.wait()
            if cancel_task:
                await asyncio.Event().wait()
            return {"type": "http.disconnect"}

        async def send(message):
            if message["type"] == "http.response.body":
                response_started.set()
                # Keep the body in flight until the listener or caller cancels it.
                await asyncio.Event().wait()

        scope = {
            "type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"},
            "method": "POST", "path": "/v1/chat/completions", "query_string": b"",
            "headers": [(b"authorization", f"Bearer {TOKEN}".encode()),
                        (b"content-type", b"application/json")],
            "client": ("127.0.0.1", 1), "server": ("test", 80), "scheme": "http",
        }
        task = asyncio.create_task(app(scope, receive, send))
        if cancel_task:
            await asyncio.wait_for(response_started.wait(), timeout=1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=1)
        else:
            await asyncio.wait_for(task, timeout=1)
        assert stream.closed == 1
        assert await app.state.concurrency.acquire(timeout=0.01)
        app.state.concurrency.release()

    asyncio.run(exercise())


def test_upstream_cleanup_has_a_deadline(monkeypatch):
    monkeypatch.setattr(openai_api, "STREAM_CLOSE_TIMEOUT_SECONDS", 0.01)

    async def exercise():
        stream = StubStream(close_delay=2)
        app = _app(StubEngine(stream=stream))
        response = await asyncio.wait_for(_post(app, stream=True), timeout=1)
        assert response.status_code == 200
        assert stream.close_started.is_set()
        assert await app.state.concurrency.acquire(timeout=0.01)
        app.state.concurrency.release()

    asyncio.run(exercise())


@pytest.mark.parametrize("key", ["short", "x" * 31, " " * 32, "x" * 513])
def test_server_rejects_invalid_compatibility_key(monkeypatch, key):
    monkeypatch.setenv("PPROUTER_API_KEY", key)
    with pytest.raises(RuntimeError, match="PPROUTER_API_KEY"):
        Settings.from_env()


def test_server_does_not_keep_plaintext_key_in_settings(monkeypatch):
    monkeypatch.setenv("PPROUTER_API_KEY", TOKEN)
    settings = Settings.from_env()
    assert settings.openai_api_key_hash == hashlib.sha256(TOKEN.encode()).digest()
    assert TOKEN not in repr(settings)

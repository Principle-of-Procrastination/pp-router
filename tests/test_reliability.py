import asyncio
import json
from datetime import datetime
from unittest.mock import patch

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from conftest import USAGE, admin_login, chat, headers
from pprouter.models import Attempt, GatewayRequest
from pprouter.providers import ProviderPool
from pprouter.records import BILLING_ZONE
from pprouter.schemas import ChatRequest
from pprouter.security import authenticate_key
from starlette.requests import Request


async def caller_for(app, creds):
    return await authenticate_key(
        Request(
            {
                "type": "http",
                "app": app,
                "headers": [(b"authorization", headers(creds)["Authorization"].encode())],
            }
        )
    )


async def test_month_boundary_filter_and_csv(env):
    app, client, _, creds = env
    for stamp in (
        datetime(2026, 10, 31, 23, 59, 59, tzinfo=BILLING_ZONE),
        datetime(2026, 11, 1, 0, 0, 0, tzinfo=BILLING_ZONE),
    ):
        with patch("pprouter.records.time.time", return_value=stamp.timestamp()):
            r = await client.post("/v1/chat/completions", headers=headers(creds), json=chat("auto"))
            assert r.status_code == 200
    await admin_login(client, creds)
    for month in ("2026-10", "2026-11"):
        r = (await client.get("/admin/v1/reports/monthly", params={"month": month})).json()
        assert r["summary"]["business_requests"] == 1
        assert r["summary"]["upstream_calls"] == 2
        assert r["summary"]["total_tokens"] == 60
        assert len(r["rows"]) == 2
    r = (await client.get("/admin/v1/reports/monthly?month=2026-11&phase=routing")).json()
    assert r["summary"]["total_tokens"] == 30
    csv = await client.get("/admin/v1/reports/monthly.csv?month=2026-11")
    assert "attachment" in csv.headers["content-disposition"]
    assert csv.text.count("2026-11") == 2
    assert (await client.get("/admin/v1/reports/monthly?month=2026-99")).status_code == 400
    r = (await client.get("/admin/v1/reports/monthly?month=2026-11&company_id=missing")).json()
    assert r["summary"]["business_requests"] == 0
    assert r["summary"]["total_tokens"] is None


async def test_stream_duplicate_usage_is_not_added_and_omitted_when_not_requested(env):
    app, client, provider, creds = env
    provider.chunks = [
        {
            "choices": [{"index": 0, "delta": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": USAGE,
        },
        {"choices": [], "usage": USAGE},
        {"choices": [], "usage": USAGE},
    ]
    response = await client.post(
        "/v1/chat/completions", headers=headers(creds), json=chat(stream=True)
    )
    assert "[DONE]" in response.text and "usage" not in response.text
    async with app.state.db.session() as session:
        rows = list(await session.scalars(select(Attempt)))
        assert len(rows) == 1 and rows[0].total_tokens == 30


async def test_cancelled_stream_releases_lease_and_records_unknown(env):
    app, _, provider, creds = env
    caller = await caller_for(app, creds)
    response = await app.state.gateway.call(ChatRequest(**chat(stream=True)), caller)
    generator = response.body_iterator
    await anext(generator)
    await generator.aclose()
    assert provider.streams[-1].closed and app.state.limits.active == 0
    async with app.state.db.session() as session:
        row = await session.scalar(select(Attempt))
        root = await session.scalar(select(GatewayRequest))
        assert row.status == root.status == "cancelled"
        assert row.total_tokens is None and not row.usage_known


async def test_concurrency_isolation_and_cancel_nonstream(env):
    app, _, provider, creds = env
    caller = await caller_for(app, creds)
    entered, wait = asyncio.Event(), asyncio.Event()
    original = provider.complete

    async def blocked(*args):
        entered.set()
        await wait.wait()
        return await original(*args)

    provider.complete = blocked
    caller.grant.concurrency = 1
    task = asyncio.create_task(app.state.gateway.call(ChatRequest(**chat()), caller))
    await entered.wait()
    with pytest.raises(Exception, match="concurrency_limit"):
        await app.state.gateway.call(ChatRequest(**chat()), caller)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert app.state.limits.active == 0
    provider.complete = original
    assert (await app.state.gateway.call(ChatRequest(**chat()), caller)).status_code == 200
    async with app.state.db.session() as session:
        rows = list(
            await session.scalars(select(GatewayRequest).order_by(GatewayRequest.started_at))
        )
        assert [r.status for r in rows] == ["cancelled", "succeeded"]


async def test_database_failure_prevents_upstream_and_recover_marks_interruption(env):
    app, _, provider, creds = env
    caller = await caller_for(app, creds)

    async def unavailable(*args):
        raise OperationalError("redacted", {}, Exception("locked"))

    with patch.object(app.state.gateway.records, "start_attempt", unavailable):
        with pytest.raises(OperationalError):
            await app.state.gateway.call(ChatRequest(**chat()), caller)
    assert not provider.calls and app.state.limits.active == 0
    await app.state.gateway.records.start_request(caller, ChatRequest(**chat()), "abandoned")
    async with app.state.db.session.begin() as session:
        session.add(
            Attempt(
                request_id="abandoned",
                ordinal=1,
                phase="completion",
                provider="kimi",
                model="kimi-k3.1-pro",
            )
        )
    await app.state.db.recover()
    async with app.state.db.session() as session:
        root = await session.get(GatewayRequest, "abandoned")
        attempt = await session.scalar(select(Attempt))
        assert root.status == attempt.status == "interrupted"
        assert not attempt.usage_known and attempt.total_tokens is None


@pytest.mark.parametrize("stream", [False, True])
async def test_real_adapter_with_mock_http_preserves_extensions(env, stream):
    app, client, _, creds = env
    received = []

    async def handler(request):
        body = json.loads(request.content)
        received.append(body)
        assert "thinking" not in body
        assert body["reasoning_effort"] == "low"
        if stream:
            chunk = {
                "id": "up",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "kimi-k3.1-pro",
                "choices": [
                    {
                        "index": 0,
                        "delta": {"content": "done", "reasoning_content": "thought"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": USAGE,
            }
            return httpx.Response(
                200,
                text="data: " + json.dumps(chunk) + "\n\ndata: [DONE]\n\n",
                headers={"content-type": "text/event-stream", "x-request-id": "mock-kimi"},
            )
        return httpx.Response(
            200,
            json={
                "id": "up",
                "object": "chat.completion",
                "created": 1,
                "model": "kimi-k3.1-pro",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "done",
                            "reasoning_content": "thought",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": USAGE,
            },
            headers={"x-request-id": "mock-kimi"},
        )

    from openai import AsyncOpenAI

    pool = ProviderPool(app.state.settings)
    pool.clients["kimi"] = AsyncOpenAI(
        api_key="test",
        base_url="https://mock/v1",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    app.state.gateway.providers = pool
    try:
        r = await client.post(
            "/v1/chat/completions",
            headers=headers(creds),
            json=chat("kimi-k3.1-pro", stream=stream),
        )
        assert r.status_code == 200, r.text
        assert "thought" in r.text
        assert len(received) == 1
        async with app.state.db.session() as session:
            row = await session.scalar(select(Attempt))
            assert row.total_tokens == 30 and row.upstream_request_id == "mock-kimi"
    finally:
        await pool.close()


async def test_real_socket_disconnect_cancels_before_response_and_during_stream(env):
    import socket
    import uvicorn
    from conftest import FakeStream

    app, _, provider, creds = env
    first = asyncio.Event()
    blocked = asyncio.Event()

    async def wait_complete(*args):
        first.set()
        await blocked.wait()

    class SlowStream(FakeStream):
        async def __aiter__(self):
            yield {"choices": [{"index": 0, "delta": {"content": "first"}}]}
            await blocked.wait()

    source = SlowStream([])

    async def slow_stream(*args):
        return source

    provider.complete = wait_complete
    provider.stream = slow_stream
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    config = uvicorn.Config(app, lifespan="off", access_log=False, log_level="error", ws="none")
    server = uvicorn.Server(config)
    # Avoid signal handler installation in the pytest runner.
    server_task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        for _ in range(100):
            if server.started:
                break
            await asyncio.sleep(0.01)
        async with httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{sock.getsockname()[1]}"
        ) as client:
            task = asyncio.create_task(
                client.post("/v1/chat/completions", headers=headers(creds), json=chat())
            )
            await asyncio.wait_for(first.wait(), 3)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            for _ in range(100):
                if app.state.limits.active == 0:
                    break
                await asyncio.sleep(0.01)
            assert app.state.limits.active == 0
            async with client.stream(
                "POST", "/v1/chat/completions", headers=headers(creds), json=chat(stream=True)
            ) as response:
                async for line in response.aiter_lines():
                    if line.startswith("data:"):
                        break
            for _ in range(100):
                if app.state.limits.active == 0:
                    break
                await asyncio.sleep(0.01)
            assert source.closed and app.state.limits.active == 0
            async with app.state.db.session() as session:
                attempts = list(await session.scalars(select(Attempt)))
                assert len(attempts) == 2
                assert all(a.status == "cancelled" and not a.usage_known for a in attempts)
    finally:
        server.should_exit = True
        await asyncio.wait_for(server_task, 5)
        sock.close()


async def test_classifier_input_budget_and_no_pixels(env):
    app, _, _, creds = env
    from pprouter.models import Model
    from pprouter.routing import classifier_messages

    caller = await caller_for(app, creds)
    request = ChatRequest(
        **chat(
            "auto",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "\n\\" * 12000},
                        {
                            "type": "image_url",
                            "image_url": {"url": "https://example.com/private-image-url.png"},
                        },
                    ],
                }
            ],
        )
    )
    async with app.state.db.session() as session:
        models = list(await session.scalars(select(Model)))
    messages = classifier_messages(request, caller, models)
    assert sum(len(m["content"]) for m in messages) <= 8000
    assert "private-image-url" not in json.dumps(messages)
    assert json.loads(messages[1]["content"])["features"]["images"]


async def test_standard_sdk_tool_message_dump_round_trip(env):
    app, client, provider, creds = env
    from openai.types.chat import ChatCompletionMessage

    message = ChatCompletionMessage(
        role="assistant",
        content=None,
        reasoning_content="carry reasoning",
        tool_calls=[
            {
                "id": "tool-sdk",
                "index": 0,
                "type": "function",
                "function": {"name": "lookup", "arguments": "{}"},
            }
        ],
    )
    provider.results.append(
        {
            "choices": [{"message": message.model_dump(), "finish_reason": "tool_calls"}],
            "usage": USAGE,
        }
    )
    tool = {"type": "function", "function": {"name": "lookup"}}
    initial = await client.post(
        "/v1/chat/completions", headers=headers(creds), json=chat("kimi-k3.1-pro", tools=[tool])
    )
    assert initial.status_code == 200
    messages = [
        {"role": "user", "content": "lookup"},
        message.model_dump(),
        {"role": "tool", "tool_call_id": "tool-sdk", "content": "ok"},
    ]
    response = await client.post(
        "/v1/chat/completions",
        headers=headers(creds),
        json=chat("auto", tools=[tool], messages=messages),
    )
    assert response.status_code == 200, response.text
    assert provider.calls[-1][1]["messages"][1]["reasoning_content"] == "carry reasoning"
    assert "index" not in provider.calls[-1][1]["messages"][1]["tool_calls"][0]


@pytest.mark.parametrize("stream", [True, False])
async def test_aborted_generation_is_failed_but_usage_is_kept(env, stream):
    app, client, provider, creds = env
    if stream:
        provider.chunks = [
            {
                "choices": [
                    {"index": 0, "delta": {"content": "partial"}, "finish_reason": "aborted"}
                ]
            },
            {"choices": [], "usage": USAGE},
        ]
    else:
        provider.results.append(
            {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "partial"},
                        "finish_reason": "aborted",
                    }
                ],
                "usage": USAGE,
            }
        )
    response = await client.post(
        "/v1/chat/completions", headers=headers(creds), json=chat(stream=stream)
    )
    assert "upstream_generation_aborted" in response.text
    assert "[DONE]" not in response.text
    async with app.state.db.session() as session:
        row = await session.scalar(select(Attempt))
        assert row.status == "failed" and row.total_tokens == 30


async def test_live_smoke_script_with_local_simulated_providers(env, tmp_path, monkeypatch):
    """Exercise the explicit verification script without claiming provider/semantic acceptance."""
    import argparse
    import socket
    import uvicorn
    from scripts import live
    from pprouter.providers import Result

    app, _, provider, credentials = env
    original = provider.complete

    async def complete(model, payload, timeout):
        if payload["messages"][0].get("role") == "system" and payload["messages"][0].get(
            "content", ""
        ).startswith("You are a routing classifier"):
            return await original(model, payload, timeout)
        if payload.get("tool_choice") == "required":
            message = {
                "role": "assistant",
                "content": None,
                "reasoning_content": "retain this",
                "tool_calls": [
                    {
                        "id": "call-" + model.id,
                        "type": "function",
                        "function": {"name": "get_weather", "arguments": '{"city":"上海"}'},
                    }
                ],
            }
            return Result(
                {
                    "id": "mock",
                    "model": model.id,
                    "object": "chat.completion",
                    "created": 1,
                    "choices": [{"index": 0, "message": message, "finish_reason": "tool_calls"}],
                    "usage": USAGE,
                }
            )
        result = await original(model, payload, timeout)
        if payload.get("response_format"):
            result.body["choices"][0]["message"]["content"] = '{"ok":true}'
        return result

    provider.complete = complete
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only")
    monkeypatch.setenv("MOONSHOT_API_KEY", "test-only")
    # Keep script reports and credentials isolated from the actual local workspace.
    (tmp_path / "tests/fixtures").mkdir(parents=True)
    (tmp_path / ".local").mkdir()
    from pathlib import Path

    fixture = Path(__file__).parent / "fixtures/red-square.png"
    (tmp_path / "tests/fixtures/red-square.png").write_bytes(fixture.read_bytes())
    monkeypatch.setattr(live, "ROOT", tmp_path)
    credential_path = tmp_path / ".local/credentials.json"
    credential_path.write_text(json.dumps(credentials))
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    server = uvicorn.Server(
        uvicorn.Config(app, lifespan="off", access_log=False, log_level="error", ws="none")
    )
    server_task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        for _ in range(100):
            if server.started:
                break
            await asyncio.sleep(0.01)
        args = argparse.Namespace(
            command="smoke",
            credentials=str(credential_path),
            base=f"http://127.0.0.1:{sock.getsockname()[1]}",
        )
        await live.run(args)
        report = json.loads((tmp_path / ".local/live-smoke.json").read_text())
        assert len(report["cases"]) == 14
        assert report["confirmed_tokens"] > 0
    finally:
        server.should_exit = True
        await asyncio.wait_for(server_task, 5)
        sock.close()

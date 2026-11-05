import copy
import json
from collections import deque

import httpx
import pytest_asyncio

from pprouter.bootstrap import initialize
from pprouter.config import Settings
from pprouter.main import create_app
from pprouter.providers import Result

USAGE = {
    "prompt_tokens": 20,
    "completion_tokens": 10,
    "total_tokens": 30,
    "prompt_cache_hit_tokens": 7,
    "completion_tokens_details": {"reasoning_tokens": 4},
}


class FakeStream:
    upstream_id = "upstream-stream"

    def __init__(self, chunks):
        self.chunks, self.closed = chunks, False

    async def __aiter__(self):
        for chunk in self.chunks:
            if isinstance(chunk, Exception):
                raise chunk
            yield chunk

    async def aclose(self):
        self.closed = True


class FakeProviders:
    def __init__(self):
        self.calls = []
        self.results = deque()
        self.classification = None
        self.chunks = None
        self.streams = []
        self.available = {"deepseek", "kimi"}

    def configured(self, name):
        return name in self.available

    async def complete(self, model, payload, timeout):
        self.calls.append((model.id, copy.deepcopy(payload)))
        if payload["messages"][0].get("role") == "system" and payload["messages"][0].get(
            "content", ""
        ).startswith("You are a routing classifier"):
            data = self.classification or {
                "task": "general",
                "needs_reasoning": False,
                "model": "deepseek-flash",
                "reason": "general_task",
            }
            if isinstance(data, Exception):
                raise data
            return Result(
                {
                    "model": model.id,
                    "choices": [{"message": {"content": json.dumps(data)}}],
                    "usage": USAGE,
                },
                "classifier-id",
            )
        if self.results:
            result = self.results.popleft()
            if isinstance(result, Exception):
                raise result
            return Result(result, "upstream-id")
        return Result(
            {
                "id": "provider-id",
                "object": "chat.completion",
                "created": 1,
                "model": model.id,
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "Hello",
                            "reasoning_content": "private reasoning",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": USAGE,
            },
            "upstream-id",
        )

    async def stream(self, model, payload, timeout):
        self.calls.append((model.id, payload))
        chunks = self.chunks or [
            {
                "object": "chat.completion.chunk",
                "created": 1,
                "model": model.id,
                "choices": [
                    {
                        "index": 0,
                        "delta": {"role": "assistant", "content": "Hello"},
                        "finish_reason": None,
                    }
                ],
            },
            {
                "object": "chat.completion.chunk",
                "created": 1,
                "model": model.id,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                "usage": USAGE,
            },
        ]
        stream = FakeStream(chunks)
        self.streams.append(stream)
        return stream

    async def close(self):
        pass


@pytest_asyncio.fixture
async def env(tmp_path):
    provider = FakeProviders()
    settings = Settings(database_path=tmp_path / "test.db")
    app = create_app(settings, provider)
    async with app.router.lifespan_context(app):
        credentials = await initialize(app.state.db, "test-password-very-long")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield app, client, provider, credentials


async def admin_login(client, credentials):
    response = await client.post("/admin/v1/auth/login", json=credentials["admin"])
    assert response.status_code == 200, response.text
    client.headers["x-csrf-token"] = response.json()["csrf_token"]


def headers(credentials, code="chat"):
    return {"Authorization": "Bearer " + credentials["applications"][code]["api_key"]}


def chat(model="deepseek-flash", **values):
    return {"model": model, "messages": [{"role": "user", "content": "Hello"}], **values}

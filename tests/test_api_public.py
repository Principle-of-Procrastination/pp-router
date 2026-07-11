import asyncio

import httpx
from fastapi import FastAPI

from pprouter import api
from pprouter.config import Settings
from pprouter.schemas import HistoryItem, HistorySummary, Usage
from pprouter.security import SlidingWindowRateLimiter


class StubHistory:
    def recent(self, limit: int) -> list[HistoryItem]:
        return [
            HistoryItem(
                ts="2026-07-11T10:00:00+08:00",
                query="private query",
                model="glm-4.7",
                tier="MEDIUM",
                usage=Usage(prompt_tokens=10, completion_tokens=20, total_tokens=30),
            )
        ][:limit]

    def summary(self) -> HistorySummary:
        return HistorySummary(total_requests=1, total_tokens=30, by_model={})


def _app() -> FastAPI:
    app = FastAPI()
    app.state.settings = Settings(
        cors_origins=("http://localhost:5173",),
        chat_requests_per_minute=30,
        global_chat_requests_per_minute=120,
        read_requests_per_minute=120,
        max_concurrent_requests=2,
        upstream_timeout_seconds=30,
        stream_heartbeat_seconds=5,
        max_output_tokens=1024,
        history_path="history.db",
        cloudbase_env_id=None,
        cloudbase_api_key=None,
        cloudbase_history_collection="pprouter_history",
    )
    app.state.history = StubHistory()
    app.state.rate_limiter = SlidingWindowRateLimiter()
    app.include_router(api.router)
    return app


def test_models_are_public_and_qwen_is_removed() -> None:
    async def exercise() -> None:
        transport = httpx.ASGITransport(app=_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/models")

            assert response.status_code == 200
            model_ids = [model["id"] for model in response.json()]
            assert model_ids == ["step-3.7-flash", "glm-4.7", "glm-5.1"]

    asyncio.run(exercise())


def test_session_endpoint_is_removed() -> None:
    async def exercise() -> None:
        transport = httpx.ASGITransport(app=_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/session", json={"access_key": "unused"})

            assert response.status_code == 404

    asyncio.run(exercise())


def test_public_history_redacts_query_text() -> None:
    async def exercise() -> None:
        transport = httpx.ASGITransport(app=_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/history?limit=1")

            assert response.status_code == 200
            assert response.json()["items"][0]["query"] == ""

    asyncio.run(exercise())


def test_history_limit_is_validated_before_store_access() -> None:
    async def exercise() -> None:
        transport = httpx.ASGITransport(app=_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/history?limit=101")

            assert response.status_code == 422

    asyncio.run(exercise())

import asyncio

import httpx
from fastapi import FastAPI

from pprouter import api
from pprouter.config import Settings
from pprouter.security import SessionManager, SlidingWindowRateLimiter


def _app() -> FastAPI:
    app = FastAPI()
    app.state.settings = Settings(
        access_key="a" * 24,
        session_secret="b" * 32,
        cors_origins=("http://localhost:5173",),
        session_ttl_seconds=300,
        login_attempts_per_minute=5,
        chat_requests_per_minute=30,
        max_concurrent_requests=2,
        upstream_timeout_seconds=30,
        stream_heartbeat_seconds=5,
        max_output_tokens=1024,
        history_path="history.db",
        cloudbase_env_id=None,
        cloudbase_api_key=None,
        cloudbase_history_collection="pprouter_history",
    )
    app.state.sessions = SessionManager("a" * 24, "b" * 32, 300)
    app.state.rate_limiter = SlidingWindowRateLimiter()
    app.include_router(api.router)
    return app


async def _authorization(client: httpx.AsyncClient) -> dict[str, str]:
    response = await client.post("/session", json={"access_key": "a" * 24})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['token']}"}


def test_models_require_session_and_qwen_is_removed() -> None:
    async def exercise() -> None:
        transport = httpx.ASGITransport(app=_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            assert (await client.get("/models")).status_code == 401

            response = await client.get("/models", headers=await _authorization(client))

            assert response.status_code == 200
            model_ids = [model["id"] for model in response.json()]
            assert model_ids == ["step-3.7-flash", "glm-4.7", "glm-5.1"]

    asyncio.run(exercise())


def test_invalid_access_key_is_rejected() -> None:
    async def exercise() -> None:
        transport = httpx.ASGITransport(app=_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/session", json={"access_key": "wrong"})

            assert response.status_code == 401

    asyncio.run(exercise())


def test_history_limit_is_validated_before_store_access() -> None:
    async def exercise() -> None:
        transport = httpx.ASGITransport(app=_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                "/history?limit=101", headers=await _authorization(client)
            )

            assert response.status_code == 422

    asyncio.run(exercise())

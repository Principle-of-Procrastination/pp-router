import json
import time

import pytest
from openai import AsyncOpenAI
from sqlalchemy import select

from conftest import USAGE, admin_login, chat, headers
from pprouter.bootstrap import initialize
from pprouter.models import AccessKey, Attempt, CompanyApplication, GatewayRequest
from pprouter.providers import UpstreamFailure, normalize_usage


async def test_bootstrap_auth_and_idempotency(env):
    app, client, _, credentials = env
    assert await initialize(app.state.db, "different-password") == {}
    await admin_login(client, credentials)
    assert (await client.get("/admin/v1/auth/me")).json()["username"] == "pp_admin"
    assert (await client.get("/admin/v1/keys")).json()[0].get("digest") is None
    client.headers.pop("x-csrf-token")
    assert (
        await client.post("/admin/v1/companies", json={"code": "x", "name": "X"})
    ).status_code == 403
    assert (
        await client.get("/admin/v1/companies", headers={"Origin": "https://evil.invalid"})
    ).status_code == 403
    assert (
        await client.get(
            "/v1/models", headers={"Authorization": "Bearer " + credentials["provisioning_api_key"]}
        )
    ).status_code == 401
    assert (
        await client.post(
            "/internal/v1/companies", headers=headers(credentials), json={"code": "x", "name": "X"}
        )
    ).status_code == 401


async def test_identity_disabled_revocation_expiry(env):
    app, client, provider, credentials = env
    await admin_login(client, credentials)
    other = (
        await client.post(
            "/admin/v1/companies", json={"code": "other", "name": "Other", "external_id": "suite2"}
        )
    ).json()
    repeated = (
        await client.post(
            "/internal/v1/companies",
            headers={"Authorization": "Bearer " + credentials["provisioning_api_key"]},
            json={"code": "other-again", "name": "Other", "external_id": "suite2"},
        )
    ).json()
    assert repeated["id"] == other["id"]
    grant = (
        await client.post(
            "/admin/v1/grants",
            json={
                "company_id": other["id"],
                "application_id": credentials["applications"]["chat"]["application_id"],
            },
        )
    ).json()
    key = (
        await client.post("/admin/v1/keys", json={"grant_id": grant["id"], "name": "other"})
    ).json()
    auth = {
        "Authorization": "Bearer " + key["secret"],
        "X-Company-ID": credentials["applications"]["chat"]["company_id"],
    }
    assert (
        await client.post("/v1/chat/completions", headers=auth, json=chat(company_id="pp_admin"))
    ).status_code == 400
    assert (await client.post("/v1/chat/completions", headers=auth, json=chat())).status_code == 200
    async with app.state.db.session() as session:
        row = await session.scalar(select(GatewayRequest))
        assert row.company_id == other["id"]
    await client.patch("/admin/v1/companies/" + other["id"], json={"enabled": False})
    assert (await client.post("/v1/chat/completions", headers=auth, json=chat())).status_code == 403
    await client.patch("/admin/v1/companies/" + other["id"], json={"enabled": True})
    async with app.state.db.session.begin() as session:
        row = await session.get(AccessKey, key["id"])
        row.expires_at = time.time() - 1
    assert (await client.get("/v1/models", headers=auth)).status_code == 401
    await client.post("/admin/v1/keys/" + key["id"] + "/revoke")
    assert len(provider.calls) == 1


async def test_openai_sdk_and_stream_usage(env):
    app, client, provider, creds = env
    sdk = AsyncOpenAI(
        api_key=creds["applications"]["chat"]["api_key"],
        base_url="http://test/v1",
        http_client=client,
        max_retries=0,
    )
    result = await sdk.chat.completions.create(**chat())
    assert result.choices[0].message.reasoning_content == "private reasoning"
    stream = await sdk.chat.completions.create(
        **chat(stream=True, stream_options={"include_usage": True})
    )
    chunks = [chunk async for chunk in stream]
    assert chunks[-1].usage.total_tokens == 30
    assert chunks[-1].choices == []
    assert provider.streams[-1].closed
    await admin_login(client, creds)
    report = (await client.get("/admin/v1/reports/monthly")).json()
    assert report["summary"]["total_tokens"] == 60
    assert report["summary"]["cached_tokens"] == 14
    assert report["summary"]["reasoning_tokens"] == 8
    assert app.state.limits.active == 0
    async with app.state.db.session() as session:
        attempts = list(await session.scalars(select(Attempt)))
        assert all("private reasoning" not in json.dumps(a.raw_usage) for a in attempts)


async def test_auto_accounts_classifier_and_failure_fallback(env):
    app, client, provider, creds = env
    response = await client.post("/v1/chat/completions", headers=headers(creds), json=chat("auto"))
    assert response.status_code == 200, response.text
    assert response.json()["usage"]["total_tokens"] == 30
    provider.classification = {"model": "outside-allowed"}
    assert (
        await client.post("/v1/chat/completions", headers=headers(creds), json=chat("auto"))
    ).status_code == 200
    await admin_login(client, creds)
    data = (await client.get("/admin/v1/reports/monthly")).json()
    assert data["summary"]["business_requests"] == 2
    assert data["summary"]["upstream_calls"] == 4
    assert data["summary"]["total_tokens"] == 120
    calls = (await client.get("/admin/v1/requests")).json()
    assert calls[0]["routing"]["reason"] == "invalid_classification"
    assert calls[0]["routing"]["degraded"]


async def test_capabilities_tools_and_reasoning_binding(env):
    app, client, provider, creds = env
    image = {
        "role": "user",
        "content": [
            {"type": "text", "text": "describe"},
            {"type": "image_url", "image_url": {"url": "https://example.com/image.png"}},
        ],
    }
    assert (
        await client.post(
            "/v1/chat/completions",
            headers=headers(creds),
            json=chat("deepseek-v4-pro", messages=[image]),
        )
    ).status_code == 400
    schema = {
        "type": "json_schema",
        "json_schema": {
            "name": "answer",
            "schema": {
                "type": "object",
                "properties": {"ok": {"type": "boolean"}},
                "required": ["ok"],
                "additionalProperties": False,
            },
        },
    }
    r = await client.post(
        "/v1/chat/completions",
        headers=headers(creds),
        json=chat("auto", messages=[image], response_format=schema),
    )
    assert r.status_code == 200, r.text
    assert provider.calls[-1][0] == "kimi-k3.1-pro"
    assert len(provider.calls) == 1
    assert "thinking" not in provider.calls[-1][1]
    assistant = {
        "role": "assistant",
        "content": None,
        "reasoning_content": "retain me",
        "tool_calls": [
            {"id": "tool1", "type": "function", "function": {"name": "weather", "arguments": "{}"}}
        ],
    }
    provider.results.append(
        {"choices": [{"message": assistant, "finish_reason": "tool_calls"}], "usage": USAGE}
    )
    tool = {"type": "function", "function": {"name": "weather", "parameters": {"type": "object"}}}
    r = await client.post(
        "/v1/chat/completions",
        headers=headers(creds),
        json=chat("kimi-k3.1-pro", tools=[tool], reasoning_effort="high"),
    )
    assert r.status_code == 200, r.text
    continuation = [
        {"role": "user", "content": "weather"},
        assistant,
        {"role": "tool", "tool_call_id": "tool1", "content": "sunny"},
    ]
    before = len(provider.calls)
    r = await client.post(
        "/v1/chat/completions",
        headers=headers(creds),
        json=chat("auto", messages=continuation, tools=[tool]),
    )
    assert r.status_code == 200, r.text
    assert len(provider.calls) == before + 1
    assert provider.calls[-1][0] == "kimi-k3.1-pro"
    assert provider.calls[-1][1]["reasoning_effort"] == "high"
    assert provider.calls[-1][1]["messages"][1]["reasoning_content"] == "retain me"
    assert (
        await client.post(
            "/v1/chat/completions",
            headers=headers(creds, "vision"),
            json=chat("auto", messages=continuation),
        )
    ).status_code == 400


async def test_retry_unknown_and_stream_failure(env):
    app, client, provider, creds = env
    provider.results.append(UpstreamFailure("upstream_rate_limit", 429, True))
    r = await client.post("/v1/chat/completions", headers=headers(creds), json=chat())
    assert r.status_code == 200
    assert [x[0] for x in provider.calls] == ["deepseek-flash", "deepseek-flash"]
    provider.results.append(UpstreamFailure("upstream_timeout", 504))
    assert (
        await client.post("/v1/chat/completions", headers=headers(creds), json=chat())
    ).status_code == 504
    assert len(provider.calls) == 3
    provider.chunks = [
        {"choices": [{"index": 0, "delta": {"content": "partial"}}]},
        UpstreamFailure("connection_lost"),
    ]
    r = await client.post("/v1/chat/completions", headers=headers(creds), json=chat(stream=True))
    assert "connection_lost" in r.text and "[DONE]" not in r.text
    assert app.state.limits.active == 0
    await admin_login(client, creds)
    data = (await client.get("/admin/v1/reports/monthly")).json()["summary"]
    assert data["usage_unknown"] == 3 and data["total_tokens"] == 30


async def test_classifier_permission_and_timeout(env):
    app, client, provider, creds = env
    provider.classification = TimeoutError()
    assert (
        await client.post("/v1/chat/completions", headers=headers(creds), json=chat("auto"))
    ).status_code == 200
    async with app.state.db.session.begin() as session:
        grant = await session.get(CompanyApplication, creds["applications"]["chat"]["grant_id"])
        grant.allowed_models = ["deepseek-v4-pro", "kimi-k3.1-pro"]
    provider.calls.clear()
    assert (
        await client.post("/v1/chat/completions", headers=headers(creds), json=chat("auto"))
    ).status_code == 200
    assert len(provider.calls) == 1
    provider.available.clear()
    assert (
        await client.post("/v1/chat/completions", headers=headers(creds), json=chat("auto"))
    ).status_code == 400


@pytest.mark.parametrize(
    "raw,known",
    [
        (None, False),
        ({}, False),
        ({"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 99}, False),
        (USAGE, True),
    ],
)
def test_usage_is_confirmed_and_nonadditive(raw, known):
    normalized = normalize_usage(raw)
    assert normalized["usage_known"] is known
    assert normalized["total_tokens"] == (30 if known else None)


async def test_routing_preview_records_only_classifier_and_enforces_identity(env):
    app, client, provider, creds = env
    payload = {"request": chat("auto"), "key_id": "unknown"}
    assert (await client.post("/admin/v1/routing/preview", json=payload)).status_code == 401
    await admin_login(client, creds)
    keys = (await client.get("/admin/v1/keys")).json()
    key = next(k for k in keys if k["grant_id"] == creds["applications"]["chat"]["grant_id"])
    payload["key_id"] = key["id"]
    response = await client.post("/admin/v1/routing/preview", json=payload)
    assert response.status_code == 200, response.text
    row = (await client.get("/admin/v1/requests/" + response.json()["request_id"])).json()
    assert row["actual_model"] is None and row["routing"]["execution_skipped"]
    assert len(row["attempts"]) == 1 and row["attempts"][0]["phase"] == "routing"
    assert row["attempts"][0]["total_tokens"] == 30 and len(provider.calls) == 1
    assert app.state.limits.active == 0
    await client.post("/admin/v1/keys/" + key["id"] + "/revoke")
    assert (await client.post("/admin/v1/routing/preview", json=payload)).status_code == 403
    assert len(provider.calls) == 1

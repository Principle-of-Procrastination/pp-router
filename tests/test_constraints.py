import asyncio
import base64
import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from conftest import USAGE, admin_login, chat, headers
from pprouter.models import Attempt, CompanyApplication
from pprouter.schemas import ChatRequest
from pprouter.providers import UpstreamFailure

CASES = json.loads((Path(__file__).parent / "fixtures/routing_cases.json").read_text())
IMAGE = (
    "data:image/png;base64,"
    + base64.b64encode((Path(__file__).parent / "fixtures/red-square.png").read_bytes()).decode()
)


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
async def test_labelled_routes_stay_inside_capability_and_permission_boundary(env, case):
    app, client, provider, creds = env
    # This is an adversarial constraint test, not a claim of real semantic accuracy.
    async with app.state.db.session.begin() as session:
        grant = await session.get(CompanyApplication, creds["applications"]["pp_chat"]["grant_id"])
        grant.allowed_models = ["deepseek-flash", "deepseek-v4-pro"]
    provider.classification = {
        "task": case["task"],
        "model": "kimi-k3.1-pro",
        "needs_reasoning": True,
        "reason": "general_task",
    }
    content = (
        [
            {"type": "text", "text": case["query"]},
            {"type": "image_url", "image_url": {"url": IMAGE}},
        ]
        if case["image"]
        else case["query"]
    )
    response = await client.post(
        "/v1/chat/completions",
        headers=headers(creds),
        json=chat("auto", messages=[{"role": "user", "content": content}]),
    )
    assert response.status_code == 200, response.text
    assert response.json()["model"] == "deepseek-flash"
    assert all(model != "kimi-k3.1-pro" for model, _ in provider.calls)
    if case["image"]:
        assert len(provider.calls) == 1


@pytest.mark.parametrize(
    "values",
    [
        {"n": 2},
        {"upstream_url": "https://evil.invalid"},
        {"api_key": "secret"},
        {"max_tokens": 1, "max_completion_tokens": 2},
        {"stream_options": {"include_usage": True}},
        {"thinking": {"type": "disabled"}, "reasoning_effort": "high", "model": "kimi-k3.1-pro"},
        {"response_format": {"type": "json_schema"}},
        {"tools": []},
        {"tool_choice": "required"},
    ],
)
async def test_unsupported_fields_and_combinations_fail_before_upstream(env, values):
    _, client, provider, creds = env
    payload = chat()
    payload.update(values)
    response = await client.post("/v1/chat/completions", headers=headers(creds), json=payload)
    assert response.status_code == 400
    assert not provider.calls


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/image.png",
        "https://127.0.0.1/a",
        "file:///tmp/a",
        "data:image/png;base64,INVALID!",
    ],
)
def test_image_validation(url):
    with pytest.raises(ValidationError):
        ChatRequest(
            **chat(
                messages=[
                    {"role": "user", "content": [{"type": "image_url", "image_url": {"url": url}}]}
                ]
            )
        )


def test_image_count_size_and_request_body():
    part = {"type": "image_url", "image_url": {"url": IMAGE}}
    with pytest.raises(ValidationError):
        ChatRequest(**chat(messages=[{"role": "user", "content": [part] * 9}]))
    with pytest.raises(ValidationError):
        ChatRequest(
            **chat(
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": "data:image/png;base64,"
                                    + base64.b64encode(b"x" * (5 * 1024 * 1024 + 1)).decode()
                                },
                            }
                        ],
                    }
                ]
            )
        )


async def test_body_limit_and_no_payload_leak(env):
    _, client, provider, creds = env
    response = await client.post(
        "/v1/chat/completions", headers=headers(creds), content=b"x" * (20 * 1024 * 1024 + 1)
    )
    assert response.status_code == 413 and not provider.calls
    response = await client.post(
        "/v1/chat/completions",
        headers=headers(creds),
        json={
            "model": "deepseek-flash",
            "messages": [{"role": "bad", "content": "private prompt"}],
        },
    )
    assert "private prompt" not in response.text


@pytest.mark.parametrize("target", ["grant", "application", "key"])
async def test_all_access_switches_apply_immediately(env, target):
    app, client, provider, creds = env
    await admin_login(client, creds)
    entry = creds["applications"]["pp_chat"]
    if target == "grant":
        async with app.state.db.session.begin() as session:
            grant = await session.get(CompanyApplication, entry["grant_id"])
            grant.enabled = False
    elif target == "application":
        await client.patch(
            "/admin/v1/applications/" + entry["application_id"], json={"enabled": False}
        )
    else:
        keys = (await client.get("/admin/v1/keys")).json()
        key = next(k for k in keys if k["grant_id"] == entry["grant_id"])
        await client.post("/admin/v1/keys/" + key["id"] + "/revoke")
    assert (
        await client.post("/v1/chat/completions", headers=headers(creds), json=chat())
    ).status_code in (401, 403)
    assert not provider.calls


async def test_concurrent_calls_and_rpm(env):
    app, client, provider, creds = env
    async with app.state.db.session.begin() as session:
        grant = await session.get(CompanyApplication, creds["applications"]["pp_chat"]["grant_id"])
        grant.concurrency = 16
        grant.rpm = 12
    responses = await asyncio.gather(
        *[
            client.post("/v1/chat/completions", headers=headers(creds), json=chat())
            for _ in range(12)
        ]
    )
    assert all(r.status_code == 200 for r in responses)
    assert len({r.headers["x-request-id"] for r in responses}) == 12
    assert (
        await client.post("/v1/chat/completions", headers=headers(creds), json=chat())
    ).status_code == 429
    assert app.state.limits.active == 0 and not app.state.limits.by_grant
    async with app.state.db.session() as session:
        attempts = list(await session.scalars(select(Attempt)))
        assert len(attempts) == 12 and sum(a.total_tokens for a in attempts) == 360


async def test_retry_fallback_same_capabilities_and_unknown_usage(env):
    app, client, provider, creds = env
    provider.results.append(UpstreamFailure("safe_failure", retryable=True))
    provider.results.append(
        {"choices": [{"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}]}
    )
    r = await client.post("/v1/chat/completions", headers=headers(creds), json=chat("auto"))
    assert r.status_code == 200 and r.json()["model"] == "kimi-k3.1-pro"
    assert "usage" not in r.json()
    async with app.state.db.session() as session:
        rows = list(await session.scalars(select(Attempt).order_by(Attempt.ordinal)))
        assert len(rows) == 3 and [r.phase for r in rows] == ["routing", "completion", "completion"]
        assert sum(r.total_tokens or 0 for r in rows) == USAGE["total_tokens"]
        assert [r.usage_known for r in rows] == [True, False, False]


async def test_grant_policy_version_and_key_rotation(env):
    app, client, _, creds = env
    await admin_login(client, creds)
    grant = (await client.get("/admin/v1/grants")).json()[0]
    update = {
        k: grant[k]
        for k in ("enabled", "allowed_models", "rpm", "concurrency", "max_output_tokens", "policy")
    }
    update["rpm"] = 7
    changed = await client.put("/admin/v1/grants/" + grant["id"], json=update)
    assert changed.json()["policy_version"] == grant["policy_version"] + 1
    all_keys = (await client.get("/admin/v1/keys")).json()
    key = next(k for k in all_keys if k["grant_id"] == creds["applications"]["pp_chat"]["grant_id"])
    replacement = (await client.post("/admin/v1/keys/" + key["id"] + "/rotate")).json()
    assert (await client.get("/v1/models", headers=headers(creds))).status_code == 401
    assert (
        await client.get("/v1/models", headers={"Authorization": "Bearer " + replacement["secret"]})
    ).status_code == 200
    assert not any("secret" in k for k in (await client.get("/admin/v1/keys")).json())


async def test_concurrent_provisioning_is_idempotent(env):
    _, client, _, creds = env
    auth = {"Authorization": "Bearer " + creds["provisioning_api_key"]}
    results = await asyncio.gather(
        *[
            client.post(
                "/internal/v1/companies",
                headers=auth,
                json={
                    "code": "parallel-company",
                    "name": "Parallel",
                    "external_id": "parallel-suite-id",
                },
            )
            for _ in range(8)
        ]
    )
    assert all(r.status_code == 200 for r in results), [r.text for r in results]
    assert len({r.json()["id"] for r in results}) == 1
    company_id = results[0].json()["id"]
    grants = await asyncio.gather(
        *[
            client.post(
                "/internal/v1/grants",
                headers=auth,
                json={
                    "company_id": company_id,
                    "application_id": creds["applications"]["pp_chat"]["application_id"],
                },
            )
            for _ in range(8)
        ]
    )
    assert all(r.status_code == 200 for r in grants), [r.text for r in grants]
    assert len({r.json()["id"] for r in grants}) == 1

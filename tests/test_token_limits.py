import json
import sqlite3

import pytest
from alembic import command
from alembic.config import Config

from conftest import admin_login, chat, headers
from pprouter.config import ROOT
from pprouter.db import migrate
from pprouter.models import CompanyApplication, Model
from pprouter.schemas import ChatRequest
from test_applications import legacy_database, snapshot


@pytest.mark.parametrize("field", ["max_tokens", "max_completion_tokens"])
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("requested", [256, 32000, 32001, 32768])
async def test_output_limit_rejects_excess_and_preserves_valid_requests(env, field, stream, requested):
    _, client, provider, credentials = env
    response = await client.post(
        "/v1/chat/completions",
        headers=headers(credentials, "pp_code"),
        json=chat("auto", stream=stream, **{field: requested}),
    )
    if requested > 32000:
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "invalid_request"
        assert not provider.calls
        return
    assert response.status_code == 200, response.text
    assert len(provider.calls) == 2
    assert provider.calls[0][1]["max_tokens"] == 256  # Classification budget stays separate.
    assert provider.calls[1][1]["max_tokens"] == requested
    assert "max_completion_tokens" not in provider.calls[1][1]
    await admin_login(client, credentials)
    requests = (await client.get("/admin/v1/requests")).json()
    detail = (await client.get(f"/admin/v1/requests/{requests[0]['id']}")).json()
    assert [attempt["total_tokens"] for attempt in detail["attempts"]] == [30, 30]


async def test_default_and_lower_grant_model_limits_are_advertised_and_enforced(env):
    app, client, provider, credentials = env
    for code in ("pp_code", "pp_chat", "pp_cad"):
        directory = (await client.get("/v1/models", headers=headers(credentials, code))).json()
        assert len(directory["data"]) == 4
        assert all(
            (m["context_tokens"], m["max_output_tokens"]) == (256000, 32000)
            for m in directory["data"]
        )
        response = await client.post(
            "/v1/chat/completions", headers=headers(credentials, code), json=chat()
        )
        assert response.status_code == 200
        assert provider.calls[-1][1]["max_tokens"] == 32000
    async with app.state.db.session.begin() as session:
        grant = await session.get(
            CompanyApplication, credentials["applications"]["pp_chat"]["grant_id"]
        )
        grant.max_output_tokens = 4096
        model = await session.get(Model, "deepseek-flash")
        model.max_output_tokens = 2048
    provider.calls.clear()
    for model, requested in (("deepseek-flash", 2049), ("kimi-k3.1-pro", 4097), ("auto", 4097)):
        response = await client.post(
            "/v1/chat/completions",
            headers=headers(credentials),
            json=chat(model, max_tokens=requested),
        )
        assert response.status_code == 400
        assert not provider.calls
    response = await client.post(
        "/v1/chat/completions", headers=headers(credentials), json=chat(max_tokens=2048)
    )
    assert response.status_code == 200
    assert provider.calls[-1][1]["max_tokens"] == 2048
    models = (await client.get("/v1/models", headers=headers(credentials))).json()["data"]
    assert {m["id"]: m["max_output_tokens"] for m in models} == {
        "auto": 2048,
        "deepseek-flash": 2048,
        "deepseek-v4-pro": 4096,
        "kimi-k3.1-pro": 4096,
    }


@pytest.mark.parametrize("model", ["auto", "deepseek-flash"])
@pytest.mark.parametrize("over", [0, 1])
async def test_context_includes_effective_output_and_rejects_before_classification(env, model, over):
    _, client, provider, credentials = env
    payload = chat(model, max_tokens=32000, messages=[{"role": "user", "content": ""}])
    overhead = ChatRequest(**payload).text_bound()
    payload["messages"][0]["content"] = "x" * (256000 - 32000 - overhead + over)
    response = await client.post(
        "/v1/chat/completions", headers=headers(credentials), json=payload
    )
    assert response.status_code == (400 if over else 200), response.text
    if over:
        assert not provider.calls
    else:
        assert provider.calls[-1][1]["max_tokens"] == 32000
        assert provider.calls[-1][1]["messages"] == payload["messages"]


async def test_admin_cannot_raise_grant_above_service_limit(env):
    _, client, _, credentials = env
    await admin_login(client, credentials)
    grant = (await client.get("/admin/v1/grants")).json()[0]
    body = {
        key: grant[key]
        for key in ("enabled", "allowed_models", "rpm", "concurrency", "max_output_tokens", "policy")
    }
    body["max_output_tokens"] = 32001
    assert (await client.put(f"/admin/v1/grants/{grant['id']}", json=body)).status_code == 400


async def test_limit_migration_preserves_keys_usage_and_can_restore_prior_limits(tmp_path):
    path = tmp_path / "previous.db"
    credentials = await legacy_database(path)
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{path}")
    command.upgrade(config, "6b5d9182c4fa")
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE models SET context_tokens=1000000, max_output_tokens=32768")
        connection.execute("UPDATE company_applications SET max_output_tokens=8192")
        connection.execute(
            "UPDATE company_applications SET max_output_tokens=32768 WHERE id=?",
            (credentials["applications"]["pp_code"]["grant_id"],),
        )
    stable = snapshot(
        path, ("companies", "applications", "access_keys", "admin_users", "requests", "attempts", "tool_bindings")
    )
    previous = snapshot(path, ("models", "company_applications", "audit_logs"))
    migrate(path)
    assert snapshot(path, stable) == stable
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT DISTINCT context_tokens,max_output_tokens FROM models"
        ).fetchall() == [(256000, 32000)]
        assert connection.execute(
            "SELECT DISTINCT max_output_tokens FROM company_applications"
        ).fetchall() == [(32000,)]
        changes = connection.execute(
            "SELECT details FROM audit_logs WHERE action='limits.update'"
        ).fetchall()
        assert len(changes) == 6
        for (raw,) in changes:
            details = json.loads(raw)
            if details["table"] == "company_applications":
                assert details["after"]["policy_version"] == details["before"]["policy_version"] + 1
        assert not connection.execute("PRAGMA foreign_key_check").fetchall()
    upgraded = snapshot(path, ("models", "company_applications", "audit_logs"))
    migrate(path)
    assert snapshot(path, upgraded) == upgraded
    command.downgrade(config, "6b5d9182c4fa")
    assert snapshot(path, previous) == previous
    assert snapshot(path, stable) == stable

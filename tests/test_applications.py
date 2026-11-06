import sqlite3
import time

import httpx
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select

from conftest import FakeProviders, chat, headers
from pprouter.bootstrap import initialize
from pprouter.catalog import APPLICATIONS, MODEL_IDS
from pprouter.config import ROOT, Settings
from pprouter.db import Database, migrate
from pprouter.main import create_app
from pprouter.models import (
    AccessKey,
    Application,
    Attempt,
    CompanyApplication,
    GatewayRequest,
    ToolBinding,
)


async def test_every_product_can_use_every_registered_model(env):
    app, client, _, credentials = env
    assert set(credentials["applications"]) == {"pp_code", "pp_chat", "pp_cad"}
    async with app.state.db.session() as session:
        products = list(await session.scalars(select(Application)))
        assert {p.code: p.name for p in products} == {p["code"]: p["name"] for p in APPLICATIONS}
        grant = await session.get(
            CompanyApplication, credentials["applications"]["pp_code"]["grant_id"]
        )
        assert grant.max_output_tokens == 32000
    for code in credentials["applications"]:
        response = await client.get("/v1/models", headers=headers(credentials, code))
        assert {m["id"] for m in response.json()["data"]} == {*MODEL_IDS, "auto"}
        for model in MODEL_IDS:
            response = await client.post(
                "/v1/chat/completions", headers=headers(credentials, code), json=chat(model)
            )
            assert response.status_code == 200, (code, model, response.text)
            assert response.json()["model"] == model


def snapshot(path, tables):
    with sqlite3.connect(path) as connection:
        return {
            table: connection.execute(f'SELECT * FROM "{table}" ORDER BY id').fetchall()
            for table in tables
        }


async def legacy_database(path):
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{path}")
    command.upgrade(config, "9350e78ae917")
    db = Database(Settings(database_path=path))
    credentials = await initialize(db, "migration-test-password")
    entry = credentials["applications"]["pp_code"]
    async with db.session.begin() as session:
        for source, legacy in (("pp_code", "agent"), ("pp_chat", "chat"), ("pp_cad", "vision")):
            item = credentials["applications"][source]
            product = await session.get(Application, item["application_id"])
            product.code = legacy
            product.name = "legacy " + legacy
            key = await session.scalar(
                select(AccessKey).where(AccessKey.grant_id == item["grant_id"])
            )
            key.name = f"pp_admin-{legacy}-local"
            key.expires_at = time.time() + 3600
        session.add(Application(id="custom-app", code="custom", name="Keep custom", enabled=False))
        grant = await session.get(CompanyApplication, entry["grant_id"])
        grant.rpm, grant.concurrency, grant.max_output_tokens, grant.policy_version = (
            77,
            3,
            32768,
            9,
        )
        key = await session.scalar(select(AccessKey).where(AccessKey.grant_id == grant.id))
        request = GatewayRequest(
            id="existing-request",
            company_id=grant.company_id,
            application_id=grant.application_id,
            grant_id=grant.id,
            key_id=key.id,
            environment="local",
            month="2026-11",
            requested_model="auto",
            actual_model="deepseek-flash",
            status="succeeded",
            routing={"preserved": True},
            finished_at=time.time(),
        )
        session.add(request)
        await session.flush()
        session.add(
            Attempt(
                request_id=request.id,
                ordinal=1,
                phase="completion",
                provider="deepseek",
                model="deepseek-flash",
                status="succeeded",
                usage_known=True,
                input_tokens=20,
                output_tokens=10,
                total_tokens=30,
            )
        )
        session.add(
            ToolBinding(
                grant_id=grant.id,
                environment="local",
                tool_call_id="existing-tool",
                model="deepseek-flash",
                mode={"thinking": {"type": "disabled"}},
                request_id=request.id,
            )
        )
    await db.close()
    return credentials


async def test_existing_identity_credentials_limits_and_usage_survive_migration(tmp_path):
    path = tmp_path / "legacy.db"
    credentials = await legacy_database(path)
    stable_tables = (
        "companies",
        "company_applications",
        "admin_users",
        "requests",
        "attempts",
        "tool_bindings",
    )
    before = snapshot(path, stable_tables)
    with sqlite3.connect(path) as connection:
        keys_before = connection.execute(
            "SELECT id, grant_id, digest, prefix, enabled, expires_at, environment FROM access_keys ORDER BY id"
        ).fetchall()
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{path}")
    command.upgrade(config, "6b5d9182c4fa")
    assert snapshot(path, stable_tables) == before
    with sqlite3.connect(path) as connection:
        assert (
            connection.execute(
                "SELECT id, grant_id, digest, prefix, enabled, expires_at, environment FROM access_keys ORDER BY id"
            ).fetchall()
            == keys_before
        )
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM audit_logs WHERE action='application.rename'"
            ).fetchone()[0]
            == 3
        )
        assert connection.execute(
            "SELECT name, enabled FROM applications WHERE code='custom'"
        ).fetchone() == ("Keep custom", 0)
        for product in APPLICATIONS:
            row = connection.execute(
                "SELECT id, name FROM applications WHERE code=?", (product["code"],)
            ).fetchone()
            assert row == (
                credentials["applications"][product["code"]]["application_id"],
                product["name"],
            )
    all_after = snapshot(path, (*stable_tables, "applications", "access_keys", "audit_logs"))
    command.upgrade(config, "6b5d9182c4fa")
    assert snapshot(path, all_after) == all_after
    app = create_app(Settings(database_path=path), FakeProviders())
    async with app.router.lifespan_context(app):
        assert await initialize(app.state.db, "another-password") == {}
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            response = await client.get("/v1/models", headers=headers(credentials, "pp_code"))
            assert response.status_code == 200
            assert {m["id"] for m in response.json()["data"]} == {*MODEL_IDS, "auto"}
            response = await client.post("/admin/v1/auth/login", json=credentials["admin"])
            assert response.status_code == 200
            report = (await client.get("/admin/v1/reports/monthly?month=2026-11")).json()
            assert report["summary"]["total_tokens"] == 30
            assert report["rows"][0]["application"] == "pp_code"


async def test_migration_refuses_duplicate_product_without_partial_changes(tmp_path):
    path = tmp_path / "conflict.db"
    await legacy_database(path)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO applications(id, code, name, description, enabled) VALUES (?, ?, ?, ?, ?)",
            ("different-id", "pp_cad", "Existing product", "preserve me", 1),
        )
    before = snapshot(path, ("applications", "access_keys", "company_applications"))
    with pytest.raises(RuntimeError, match="pp_cad already exists"):
        migrate(path)
    assert snapshot(path, before) == before
    with sqlite3.connect(path) as connection:
        assert (
            connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
            == "9350e78ae917"
        )

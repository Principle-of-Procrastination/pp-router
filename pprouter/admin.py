import asyncio
import secrets
import time
from typing import Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import Field
from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert

from pprouter.catalog import DEFAULT_POLICY, MODEL_IDS
from pprouter.errors import GatewayError
from pprouter.limits import OUTPUT_TOKENS
from pprouter.models import (
    AccessKey,
    AdminSession,
    AdminUser,
    Application,
    Attempt,
    AuditLog,
    Company,
    CompanyApplication,
    GatewayRequest,
    Model,
)
from pprouter.schemas import ChatRequest, StrictModel
from pprouter.security import (
    COOKIE,
    Caller,
    access_key,
    admin_actor,
    check_origin,
    digest,
    new_key,
    provisioning_actor,
    verify_password,
)

admin = APIRouter(prefix="/admin/v1", dependencies=[Depends(admin_actor)])
internal = APIRouter(prefix="/internal/v1", dependencies=[Depends(provisioning_actor)])
auth = APIRouter(prefix="/admin/v1/auth")


def public(row):
    blocked = {"password_hash", "digest", "csrf_token"}
    return {c.name: getattr(row, c.name) for c in row.__table__.columns if c.name not in blocked}


async def actor(request):
    if request.url.path.startswith("/internal/"):
        return await provisioning_actor(request)
    return f"admin:{request.state.admin_user.id}"


def audit(session, who, action, target, details=None):
    session.add(AuditLog(actor=who, action=action, target=target, details=details or {}))


async def get(session, cls, id):
    row = await session.get(cls, id)
    if row is None:
        raise GatewayError(404, "not_found", "Record not found.")
    return row


class Login(StrictModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=256)


@auth.post("/login")
async def login(body: Login, request: Request, response: Response):
    check_origin(request)
    request.app.state.limits.rate(
        "login:" + (request.client.host if request.client else "local"), 10
    )
    db = request.app.state.db
    async with db.session.begin() as session:
        user = await session.scalar(select(AdminUser).where(AdminUser.username == body.username))
        encoded = user.password_hash if user else request.app.state.dummy_hash
        valid = await asyncio.to_thread(verify_password, encoded, body.password)
        if not user or not valid or not user.enabled:
            raise GatewayError(401, "invalid_credentials", "Username or password is incorrect.")
        await session.execute(delete(AdminSession).where(AdminSession.expires_at <= time.time()))
        old = request.cookies.get(COOKIE)
        if old:
            await session.execute(delete(AdminSession).where(AdminSession.digest == digest(old)))
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        session.add(
            AdminSession(
                user_id=user.id,
                digest=digest(token),
                csrf_token=csrf,
                expires_at=time.time() + request.app.state.settings.session_seconds,
            )
        )
        audit(session, f"admin:{user.id}", "login", user.id)
    response.set_cookie(
        COOKIE,
        token,
        httponly=True,
        samesite="strict",
        secure=request.app.state.settings.cookie_secure,
        max_age=request.app.state.settings.session_seconds,
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"
    return {"username": user.username, "csrf_token": csrf}


@admin.get("/auth/me")
async def me(request: Request):
    return {
        "username": request.state.admin_user.username,
        "csrf_token": request.state.admin_session.csrf_token,
    }


@admin.post("/auth/logout")
async def logout(request: Request, response: Response):
    async with request.app.state.db.session.begin() as session:
        await session.execute(
            delete(AdminSession).where(AdminSession.id == request.state.admin_session.id)
        )
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


class CompanyInput(StrictModel):
    code: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    name: str = Field(min_length=1, max_length=160)
    external_id: str | None = Field(default=None, min_length=1, max_length=160)


class Enabled(StrictModel):
    enabled: bool


@admin.get("/companies")
async def companies(request: Request):
    async with request.app.state.db.session() as session:
        return [
            public(x) for x in await session.scalars(select(Company).order_by(Company.created_at))
        ]


@admin.post("/companies")
@internal.post("/companies")
async def create_company(body: CompanyInput, request: Request):
    who = await actor(request)
    async with request.app.state.db.session.begin() as session:
        if body.external_id:
            row = await session.scalar(
                insert(Company)
                .values(**body.model_dump())
                .on_conflict_do_nothing(index_elements=[Company.external_id])
                .returning(Company)
            )
            if row is None:
                row = await session.scalar(
                    select(Company).where(Company.external_id == body.external_id)
                )
                return public(row)
        else:
            row = Company(**body.model_dump())
            session.add(row)
            await session.flush()
        audit(session, who, "company.create", row.id)
        return public(row)


@admin.patch("/companies/{id}")
@internal.patch("/companies/{id}")
async def update_company(id: str, body: Enabled, request: Request):
    who = await actor(request)
    async with request.app.state.db.session.begin() as session:
        row = await get(session, Company, id)
        row.enabled = body.enabled
        audit(session, who, "company.update", id, body.model_dump())
        return public(row)


class AppInput(StrictModel):
    code: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=2000)


@admin.get("/applications")
async def applications(request: Request):
    async with request.app.state.db.session() as session:
        return [public(x) for x in await session.scalars(select(Application))]


@admin.post("/applications")
async def create_application(body: AppInput, request: Request):
    async with request.app.state.db.session.begin() as session:
        row = Application(**body.model_dump())
        session.add(row)
        await session.flush()
        audit(session, await actor(request), "application.create", row.id)
        return public(row)


@admin.patch("/applications/{id}")
async def update_application(id: str, body: Enabled, request: Request):
    async with request.app.state.db.session.begin() as session:
        row = await get(session, Application, id)
        row.enabled = body.enabled
        audit(session, await actor(request), "application.update", id, body.model_dump())
        return public(row)


class Policy(StrictModel):
    classifier_model: Literal["deepseek-flash"] = "deepseek-flash"
    default_model: str = "deepseek-flash"
    fallback_order: list[str] = Field(
        default_factory=lambda: list(MODEL_IDS), min_length=1, max_length=3
    )
    task_routes: dict[str, str] = Field(default_factory=lambda: dict(DEFAULT_POLICY["task_routes"]))


class GrantSettings(StrictModel):
    enabled: bool = True
    allowed_models: list[str] = Field(
        default_factory=lambda: list(MODEL_IDS), min_length=1, max_length=3
    )
    rpm: int = Field(default=60, ge=1, le=10000)
    concurrency: int = Field(default=4, ge=1, le=128)
    max_output_tokens: int = Field(default=OUTPUT_TOKENS, ge=256, le=OUTPUT_TOKENS)
    policy: Policy = Field(default_factory=Policy)

    def checked(self):
        values = self.allowed_models + [self.policy.default_model, self.policy.classifier_model]
        values += self.policy.fallback_order + list(self.policy.task_routes.values())
        if any(v not in MODEL_IDS for v in values):
            raise GatewayError(400, "invalid_model", "Policy contains an unknown model.")
        if self.policy.default_model not in self.allowed_models:
            raise GatewayError(400, "invalid_policy", "Default model must be authorized.")
        if set(self.policy.task_routes) - set(DEFAULT_POLICY["task_routes"]):
            raise GatewayError(400, "invalid_policy", "Policy contains an unknown task category.")
        return self.model_dump()


class GrantInput(GrantSettings):
    company_id: str
    application_id: str


@admin.get("/grants")
async def grants(request: Request):
    async with request.app.state.db.session() as session:
        return [public(x) for x in await session.scalars(select(CompanyApplication))]


@admin.post("/grants")
@internal.post("/grants")
async def create_grant(body: GrantInput, request: Request):
    values = body.checked()
    who = await actor(request)
    async with request.app.state.db.session.begin() as session:
        await get(session, Company, body.company_id)
        await get(session, Application, body.application_id)
        row = await session.scalar(
            insert(CompanyApplication)
            .values(**values)
            .on_conflict_do_nothing(
                index_elements=[CompanyApplication.company_id, CompanyApplication.application_id]
            )
            .returning(CompanyApplication)
        )
        if row is None:
            row = await session.scalar(
                select(CompanyApplication).where(
                    CompanyApplication.company_id == body.company_id,
                    CompanyApplication.application_id == body.application_id,
                )
            )
            return public(row)
        audit(session, who, "grant.create", row.id)
        return public(row)


@admin.put("/grants/{id}")
@internal.put("/grants/{id}")
async def update_grant(id: str, body: GrantSettings, request: Request):
    values = body.checked()
    who = await actor(request)
    async with request.app.state.db.session.begin() as session:
        row = await get(session, CompanyApplication, id)
        for key, value in values.items():
            setattr(row, key, value)
        row.policy_version += 1
        audit(session, who, "grant.update", id, values)
        return public(row)


class KeyInput(StrictModel):
    grant_id: str | None = None
    name: str = Field(min_length=1, max_length=80)
    environment: str = Field(default="local", pattern=r"^[a-zA-Z0-9_-]{1,32}$")
    expires_at: float | None = None


@admin.get("/keys")
async def keys(request: Request):
    async with request.app.state.db.session() as session:
        return [
            public(x)
            for x in await session.scalars(select(AccessKey).order_by(AccessKey.created_at.desc()))
        ]


@admin.post("/keys")
@internal.post("/keys")
async def issue_key(body: KeyInput, request: Request):
    who = await actor(request)
    if who.startswith("service:") and body.grant_id is None:
        raise GatewayError(403, "forbidden", "Only admins may issue provisioning credentials.")
    if body.expires_at is not None and body.expires_at <= time.time():
        raise GatewayError(400, "invalid_expiry", "Expiry must be in the future.")
    async with request.app.state.db.session.begin() as session:
        if body.grant_id:
            await get(session, CompanyApplication, body.grant_id)
        raw = new_key("application" if body.grant_id else "provisioning")
        row = access_key(raw, **body.model_dump())
        session.add(row)
        await session.flush()
        audit(session, who, "key.issue", row.id)
        return {**public(row), "secret": raw}


@admin.post("/keys/{id}/revoke")
@internal.post("/keys/{id}/revoke")
async def revoke(id: str, request: Request):
    who = await actor(request)
    async with request.app.state.db.session.begin() as session:
        row = await get(session, AccessKey, id)
        if who.startswith("service:") and row.kind != "application":
            raise GatewayError(403, "forbidden", "Only admins may revoke provisioning credentials.")
        row.enabled = False
        audit(session, who, "key.revoke", id)
    return {"ok": True}


@admin.post("/keys/{id}/rotate")
async def rotate(id: str, request: Request):
    async with request.app.state.db.session.begin() as session:
        row = await get(session, AccessKey, id)
        row.enabled = False
        raw = new_key(row.kind)
        replacement = access_key(
            raw,
            name=row.name,
            grant_id=row.grant_id,
            environment=row.environment,
            expires_at=row.expires_at,
        )
        session.add(replacement)
        await session.flush()
        audit(session, await actor(request), "key.rotate", id, {"replacement_id": replacement.id})
        return {**public(replacement), "secret": raw}


@admin.get("/models")
async def models(request: Request):
    async with request.app.state.db.session() as session:
        return [
            {**public(x), "configured": request.app.state.providers.configured(x.provider)}
            for x in await session.scalars(select(Model))
        ]


@admin.patch("/models/{id}")
async def update_model(id: str, body: Enabled, request: Request):
    async with request.app.state.db.session.begin() as session:
        row = await get(session, Model, id)
        row.enabled = body.enabled
        audit(session, await actor(request), "model.update", id, body.model_dump())
        return public(row)


@admin.get("/requests")
async def requests(
    request: Request,
    company_id: str | None = None,
    application_id: str | None = None,
    status: str | None = None,
    offset: int = 0,
):
    query = select(GatewayRequest)
    for key, value in {
        "company_id": company_id,
        "application_id": application_id,
        "status": status,
    }.items():
        if value:
            query = query.where(getattr(GatewayRequest, key) == value)
    async with request.app.state.db.session() as session:
        return [
            public(x)
            for x in await session.scalars(
                query.order_by(GatewayRequest.started_at.desc()).limit(50).offset(max(0, offset))
            )
        ]


@admin.get("/requests/{id}")
async def request_detail(id: str, request: Request):
    async with request.app.state.db.session() as session:
        row = await get(session, GatewayRequest, id)
        attempts = await session.scalars(
            select(Attempt).where(Attempt.request_id == id).order_by(Attempt.ordinal)
        )
        return {**public(row), "attempts": [public(x) for x in attempts]}


@admin.get("/audit")
async def audits(request: Request):
    async with request.app.state.db.session() as session:
        return [
            public(x)
            for x in await session.scalars(
                select(AuditLog).order_by(AuditLog.created_at.desc()).limit(200)
            )
        ]


class Playground(StrictModel):
    key_id: str
    request: ChatRequest


async def playground_caller(body: Playground, request: Request):
    async with request.app.state.db.session() as session:
        key = await get(session, AccessKey, body.key_id)
        if (
            key.kind != "application"
            or not key.enabled
            or (key.expires_at and key.expires_at <= time.time())
        ):
            raise GatewayError(403, "invalid_api_key", "Select an active application key.")
        grant = await get(session, CompanyApplication, key.grant_id)
        company = await get(session, Company, grant.company_id)
        application = await get(session, Application, grant.application_id)
        if not (grant.enabled and company.enabled and application.enabled):
            raise GatewayError(403, "access_disabled", "Company or application access is disabled.")
        return Caller(key, grant, company, application)


@admin.post("/playground")
async def playground(body: Playground, request: Request):
    caller = await playground_caller(body, request)
    return await request.app.state.gateway.handle(request, body.request, caller)


@admin.post("/routing/preview")
async def routing_preview(body: Playground, request: Request):
    caller = await playground_caller(body, request)
    return await request.app.state.gateway.handle(request, body.request, caller, routing_only=True)

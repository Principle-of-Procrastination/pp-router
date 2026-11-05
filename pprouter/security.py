import asyncio
import hashlib
import secrets
import time
from collections import deque
from dataclasses import dataclass

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Request
from sqlalchemy import select

from pprouter.errors import GatewayError
from pprouter.models import (
    AccessKey,
    AdminSession,
    AdminUser,
    Application,
    Company,
    CompanyApplication,
)

PASSWORDS = PasswordHasher()
COOKIE = "pp_session"


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def new_key(kind: str = "application") -> str:
    return ("ppk_" if kind == "application" else "ppi_") + secrets.token_urlsafe(32)


def access_key(
    raw: str,
    *,
    name: str,
    grant_id: str | None = None,
    environment: str = "local",
    expires_at: float | None = None,
) -> AccessKey:
    return AccessKey(
        kind="application" if grant_id else "provisioning",
        grant_id=grant_id,
        name=name,
        environment=environment,
        prefix=raw[:12],
        digest=digest(raw),
        expires_at=expires_at,
    )


def verify_password(encoded: str, password: str) -> bool:
    try:
        return PASSWORDS.verify(encoded, password)
    except (VerificationError, InvalidHashError):
        return False


def bearer(request: Request) -> str:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token or len(token) > 256:
        raise GatewayError(401, "invalid_api_key", "A valid Bearer API key is required.")
    return token


@dataclass
class Caller:
    key: AccessKey
    grant: CompanyApplication
    company: Company
    application: Application


async def authenticate_key(request: Request) -> Caller:
    token = bearer(request)
    async with request.app.state.db.session() as session:
        key = await session.scalar(select(AccessKey).where(AccessKey.digest == digest(token)))
        if (
            not key
            or key.kind != "application"
            or not key.enabled
            or (key.expires_at is not None and key.expires_at <= time.time())
        ):
            raise GatewayError(401, "invalid_api_key", "API key is invalid, expired or revoked.")
        grant = await session.get(CompanyApplication, key.grant_id)
        company = await session.get(Company, grant.company_id)
        application = await session.get(Application, grant.application_id)
        if not grant.enabled or not company.enabled or not application.enabled:
            raise GatewayError(403, "access_disabled", "Company or application access is disabled.")
        return Caller(key, grant, company, application)


async def provisioning_actor(request: Request) -> str:
    token = bearer(request)
    async with request.app.state.db.session() as session:
        key = await session.scalar(select(AccessKey).where(AccessKey.digest == digest(token)))
        if (
            not key
            or key.kind != "provisioning"
            or not key.enabled
            or (key.expires_at is not None and key.expires_at <= time.time())
        ):
            raise GatewayError(401, "invalid_service_key", "A provisioning credential is required.")
        return f"service:{key.id}"


def check_origin(request: Request):
    origin = request.headers.get("origin")
    if origin and origin.rstrip("/") not in request.app.state.settings.allowed_origins:
        raise GatewayError(403, "origin_not_allowed", "Origin is not allowed.")


async def admin_actor(request: Request) -> str:
    check_origin(request)
    token = request.cookies.get(COOKIE, "")
    async with request.app.state.db.session() as session:
        auth = await session.scalar(
            select(AdminSession).where(AdminSession.digest == digest(token))
        )
        if not auth or auth.expires_at <= time.time():
            raise GatewayError(401, "login_required", "Please sign in to the admin console.")
        user = await session.get(AdminUser, auth.user_id)
        if not user or not user.enabled:
            raise GatewayError(401, "login_required", "Admin account is disabled.")
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            csrf = request.headers.get("x-csrf-token", "")
            if not secrets.compare_digest(csrf, auth.csrf_token):
                raise GatewayError(403, "csrf_failed", "CSRF token is missing or invalid.")
        request.state.admin_session = auth
        request.state.admin_user = user
        return f"admin:{user.id}"


class Limits:
    """Single-process admission; all acquisition and release is synchronous on the event loop."""

    def __init__(self, maximum: int):
        self.maximum = maximum
        self.active = 0
        self.by_grant: dict[str, int] = {}
        self.events: dict[str, deque] = {}
        self.checks = 0

    def rate(self, key: str, limit: int):
        now = time.monotonic()
        self.checks += 1
        if self.checks % 128 == 0:
            self.events = {k: v for k, v in self.events.items() if v and v[-1] > now - 60}
        events = self.events.setdefault(key, deque())
        while events and events[0] <= now - 60:
            events.popleft()
        if len(events) >= limit:
            raise GatewayError(
                429,
                "rate_limit_exceeded",
                "Request rate limit exceeded.",
                retry_after=max(1, int(61 - now + events[0])),
            )
        events.append(now)

    def acquire(self, caller: Caller):
        key = caller.grant.id
        self.rate(f"grant:{key}", caller.grant.rpm)
        if self.active >= self.maximum or self.by_grant.get(key, 0) >= caller.grant.concurrency:
            raise GatewayError(
                429, "concurrency_limit", "Concurrent request limit exceeded.", retry_after=1
            )
        self.active += 1
        self.by_grant[key] = self.by_grant.get(key, 0) + 1
        released = False

        def release():
            nonlocal released
            if not released:
                released = True
                self.active -= 1
                self.by_grant[key] -= 1
                if self.by_grant[key] == 0:
                    del self.by_grant[key]

        return release


async def hash_password(password: str) -> str:
    return await asyncio.to_thread(PASSWORDS.hash, password)

import asyncio
import fcntl
import re
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from pprouter.admin import admin, auth, internal
from pprouter.config import Settings
from pprouter.db import Database, migrate
from pprouter.errors import GatewayError
from pprouter.gateway import Gateway
from pprouter.limits import CONTEXT_TOKENS, OUTPUT_TOKENS
from pprouter.models import Model
from pprouter.providers import ProviderPool
from pprouter import reports  # noqa: F401  register report routes
from pprouter.schemas import ChatRequest
from pprouter.security import Limits, authenticate_key, hash_password


class BodyLimit:
    def __init__(self, app, maximum):
        self.app, self.maximum = app, maximum

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        parts, size = [], 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            size += len(message.get("body", b""))
            if size > self.maximum:
                response = JSONResponse(
                    GatewayError(
                        413, "request_too_large", "Request body exceeds 20 MiB."
                    ).payload(),
                    status_code=413,
                )
                return await response(scope, receive, send)
            parts.append(message.get("body", b""))
            if not message.get("more_body", False):
                break
        consumed = False

        async def replay():
            nonlocal consumed
            if not consumed:
                consumed = True
                return {"type": "http.request", "body": b"".join(parts), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


def create_app(settings=None, providers=None):
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app):
        settings.database_path.parent.mkdir(parents=True, exist_ok=True)
        lock = open(str(settings.database_path) + ".lock", "a")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lock.close()
            raise RuntimeError(
                "Database already has a running gateway. Use one backend process."
            ) from None
        db = None
        pool = None
        try:
            await asyncio.to_thread(migrate, settings.database_path)
            db = Database(settings)
            await db.recover()
            pool = providers or ProviderPool(settings)
            app.state.settings, app.state.db, app.state.providers = settings, db, pool
            app.state.limits = Limits(settings.max_concurrent)
            app.state.dummy_hash = await hash_password("invalid-login-placeholder")
            app.state.gateway = Gateway(db, settings, pool, app.state.limits)
            yield
        finally:
            if pool:
                await pool.close()
            if db:
                await db.close()
            lock.close()

    app = FastAPI(title="pp-router", version="1.0.0", lifespan=lifespan)
    app.add_middleware(BodyLimit, maximum=settings.max_body_bytes)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.allowed_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH"],
        allow_headers=["Authorization", "Content-Type", "X-CSRF-Token", "X-Trace-ID"],
        expose_headers=["X-Request-ID", "Retry-After"],
    )

    @app.middleware("http")
    async def headers(request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(GatewayError)
    async def gateway_error(request, exc):
        headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else {}
        if exc.request_id:
            headers["X-Request-ID"] = exc.request_id
        return JSONResponse(exc.payload(), status_code=exc.status, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # Never echo a request body, inline image, prompt or secret in an error response.
        fields = ", ".join(".".join(str(x) for x in error["loc"]) for error in exc.errors()[:5])
        return JSONResponse(
            GatewayError(400, "invalid_request", "Invalid fields: " + fields).payload(),
            status_code=400,
        )

    @app.exception_handler(IntegrityError)
    async def conflict(request, exc):
        return JSONResponse(
            GatewayError(409, "conflict", "Record already exists or conflicts.").payload(),
            status_code=409,
        )

    @app.exception_handler(SQLAlchemyError)
    async def unavailable(request, exc):
        return JSONResponse(
            GatewayError(
                503,
                "storage_unavailable",
                "Storage is unavailable; new upstream calls are blocked.",
            ).payload(),
            status_code=503,
        )

    @app.get("/health")
    async def health():
        async with app.state.db.session() as session:
            await session.execute(text("SELECT 1"))
        return {
            "status": "ok",
            "providers": {p: app.state.providers.configured(p) for p in ("deepseek", "kimi")},
        }

    @app.get("/v1/models")
    async def models(caller=Depends(authenticate_key)):
        async with app.state.db.session() as session:
            models = await session.scalars(select(Model).where(Model.enabled.is_(True)))
            items = [
                {
                    "id": m.id,
                    "object": "model",
                    "created": 0,
                    "owned_by": m.provider,
                    "context_tokens": min(m.context_tokens, CONTEXT_TOKENS),
                    "max_output_tokens": min(
                        m.max_output_tokens, caller.grant.max_output_tokens, OUTPUT_TOKENS
                    ),
                }
                for m in models
                if m.id in caller.grant.allowed_models
                and app.state.providers.configured(m.provider)
            ]
        if items:
            items.insert(
                0,
                {
                    "id": "auto",
                    "object": "model",
                    "created": 0,
                    "owned_by": "pp-router",
                    "context_tokens": min(m["context_tokens"] for m in items),
                    "max_output_tokens": min(m["max_output_tokens"] for m in items),
                },
            )
        return {"object": "list", "data": items}

    @app.post("/v1/chat/completions")
    async def completions(body: ChatRequest, request: Request, caller=Depends(authenticate_key)):
        trace = request.headers.get("x-trace-id")
        if trace and not re.fullmatch(r"[a-zA-Z0-9_.:-]{1,128}", trace):
            raise GatewayError(400, "invalid_trace_id", "Trace ID must be a short identifier.")
        return await app.state.gateway.handle(request, body, caller, trace)

    app.include_router(auth)
    app.include_router(admin)
    app.include_router(internal)
    return app


app = create_app()

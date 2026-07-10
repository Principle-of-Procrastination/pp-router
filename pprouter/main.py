from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from pprouter import api
from pprouter.config import Settings, docs_enabled, get_cors_origins
from pprouter.history import CloudBaseHistoryStore, SQLiteHistoryStore
from pprouter.router_engine import build_router
from pprouter.routing import DifficultyRouter
from pprouter.security import ConcurrencyGate, SessionManager, SlidingWindowRateLimiter

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings.from_env()
    router = build_router()
    if settings.cloudbase_env_id and settings.cloudbase_api_key:
        history = CloudBaseHistoryStore(
            settings.cloudbase_env_id,
            settings.cloudbase_api_key,
            settings.cloudbase_history_collection,
        )
    else:
        history = SQLiteHistoryStore(Path(settings.history_path))

    app.state.settings = settings
    app.state.router = router
    app.state.difficulty = DifficultyRouter(router)
    app.state.history = history
    app.state.sessions = SessionManager(
        settings.access_key,
        settings.session_secret,
        settings.session_ttl_seconds,
    )
    app.state.rate_limiter = SlidingWindowRateLimiter()
    app.state.concurrency = ConcurrencyGate(settings.max_concurrent_requests)
    try:
        yield
    finally:
        history.close()


_docs_enabled = docs_enabled()
app = FastAPI(
    title="pp-router",
    version="0.2.0",
    lifespan=lifespan,
    docs_url="/docs" if _docs_enabled else None,
    redoc_url="/redoc" if _docs_enabled else None,
    openapi_url="/openapi.json" if _docs_enabled else None,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(get_cors_origins()),
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
)


@app.middleware("http")
async def attach_request_id(request: Request, call_next):
    incoming = request.headers.get("x-request-id", "")
    request_id = incoming[:64] if incoming and incoming.isascii() else uuid4().hex
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


app.include_router(api.router)

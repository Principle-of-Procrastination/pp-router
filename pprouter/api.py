import asyncio
import copy
import inspect
import json
import logging
from contextlib import suppress
from datetime import datetime
from typing import Any, AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from pprouter.config import BUILTIN_MODELS, MODEL_COMPLETION_KWARGS, Settings, Tier
from pprouter.history import HistoryStoreError
from pprouter.schemas import (
    ChatRequest,
    ChatResponse,
    HealthResponse,
    HistoryItem,
    HistoryResponse,
    ModelInfo,
    RoutingInfo,
    SessionRequest,
    SessionResponse,
    SessionStatus,
    Usage,
)
from pprouter.security import SessionClaims, client_address, require_session


logger = logging.getLogger(__name__)
router = APIRouter()
_HEARTBEAT = object()


class ClientDisconnected(Exception):
    pass


@router.get("/health")
def health() -> HealthResponse:
    return HealthResponse()


@router.post("/session")
async def create_session(req: SessionRequest, request: Request) -> SessionResponse:
    settings: Settings = request.app.state.settings
    address = client_address(request)
    await _enforce_rate_limit(
        request,
        f"login-ip:{address}",
        settings.login_attempts_per_minute,
    )
    await _enforce_rate_limit(
        request,
        "login-global",
        settings.login_attempts_per_minute * 4,
    )
    if not request.app.state.sessions.verify_access_key(req.access_key):
        await asyncio.sleep(0.15)
        raise HTTPException(status_code=401, detail="invalid access key")
    token, expires_at = request.app.state.sessions.issue()
    return SessionResponse(token=token, expires_at=expires_at)


@router.get("/session")
def session_status(
    claims: SessionClaims = Depends(require_session),
) -> SessionStatus:
    return SessionStatus(authenticated=True, expires_at=claims.expires_at)


@router.get("/models")
def list_models(
    _claims: SessionClaims = Depends(require_session),
) -> list[ModelInfo]:
    return [
        ModelInfo(id=m.id, litellm_model=m.litellm_model, tiers=[t.value for t in m.tiers])
        for m in BUILTIN_MODELS
    ]


@router.post("/chat")
async def chat(
    req: ChatRequest,
    request: Request,
    claims: SessionClaims = Depends(require_session),
) -> ChatResponse:
    settings: Settings = request.app.state.settings
    await _enforce_rate_limit(
        request,
        f"chat:{claims.subject}",
        settings.chat_requests_per_minute,
    )
    if not await request.app.state.concurrency.acquire():
        raise HTTPException(
            status_code=429,
            detail="too many concurrent requests",
            headers={"Retry-After": "1"},
        )

    engine = request.app.state.router
    messages = req.to_messages()
    routing = _resolve_routing(req, request)
    completion_kwargs = _completion_kwargs(routing, settings)
    request_id = _request_id(request)

    try:
        resp = await asyncio.wait_for(
            engine.acompletion(
                model=routing.target_group,
                messages=messages,
                **completion_kwargs,
            ),
            timeout=settings.upstream_timeout_seconds + 1,
        )
        result = ChatResponse(
            content=_extract_content(resp),
            model=getattr(resp, "model", None) or routing.target_group,
            routing=routing,
            usage=_extract_usage(resp),
        )
    except asyncio.TimeoutError as exc:
        logger.warning("upstream timeout request_id=%s", request_id)
        raise _upstream_error(504, "upstream_timeout", request_id) from exc
    except Exception as exc:
        logger.exception("upstream request failed request_id=%s", request_id)
        raise _upstream_error(502, "upstream_error", request_id) from exc
    finally:
        request.app.state.concurrency.release()

    await _record(request, messages, result)
    return result


@router.post("/chat/stream")
async def chat_stream(
    req: ChatRequest,
    request: Request,
    claims: SessionClaims = Depends(require_session),
) -> StreamingResponse:
    settings: Settings = request.app.state.settings
    await _enforce_rate_limit(
        request,
        f"chat:{claims.subject}",
        settings.chat_requests_per_minute,
    )
    if not await request.app.state.concurrency.acquire():
        raise HTTPException(
            status_code=429,
            detail="too many concurrent requests",
            headers={"Retry-After": "1"},
        )

    engine = request.app.state.router
    messages = req.to_messages()
    routing = _resolve_routing(req, request)
    completion_kwargs = _completion_kwargs(routing, settings)
    request_id = _request_id(request)

    async def events() -> AsyncIterator[str]:
        yield _sse({"type": "routing", "routing": routing.model_dump()})
        parts: list[str] = []
        usage = _empty_usage()
        model_used = routing.target_group
        try:
            stream = await engine.acompletion(
                model=routing.target_group,
                messages=messages,
                stream=True,
                stream_options={"include_usage": True},
                **completion_kwargs,
            )
            async for chunk in _iterate_stream(
                stream,
                request,
                heartbeat_seconds=settings.stream_heartbeat_seconds,
                timeout_seconds=settings.upstream_timeout_seconds,
            ):
                if chunk is _HEARTBEAT:
                    yield ": ping\n\n"
                    continue

                model_used = getattr(chunk, "model", None) or model_used
                choices = getattr(chunk, "choices", None) or []
                if choices:
                    delta = choices[0].delta
                    piece = getattr(delta, "content", None)
                    if piece:
                        parts.append(piece)
                        yield _sse({"type": "delta", "content": piece})
                    reasoning = getattr(delta, "reasoning_content", None)
                    if reasoning:
                        yield _sse({"type": "reasoning", "content": reasoning})
                chunk_usage = getattr(chunk, "usage", None)
                if chunk_usage:
                    usage = _usage_from(chunk_usage)
        except ClientDisconnected:
            logger.info("client disconnected request_id=%s", request_id)
            return
        except asyncio.TimeoutError:
            logger.warning("upstream stream timeout request_id=%s", request_id)
            yield _sse(
                {
                    "type": "error",
                    "detail": f"upstream timeout (request_id={request_id})",
                }
            )
            return
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("upstream stream failed request_id=%s", request_id)
            yield _sse(
                {
                    "type": "error",
                    "detail": f"upstream request failed (request_id={request_id})",
                }
            )
            return
        finally:
            request.app.state.concurrency.release()

        result = ChatResponse(
            content="".join(parts).strip(),
            model=model_used,
            routing=routing,
            usage=usage,
        )
        await _record(request, messages, result)
        yield _sse(
            {
                "type": "done",
                "model": model_used,
                "routing": routing.model_dump(),
                "usage": usage.model_dump(),
            }
        )

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/history")
def history(
    request: Request,
    limit: int = Query(default=50, ge=1, le=100),
    _claims: SessionClaims = Depends(require_session),
) -> HistoryResponse:
    request_id = _request_id(request)
    try:
        summary = request.app.state.history.summary()
        items = request.app.state.history.recent(limit)
    except HistoryStoreError as exc:
        logger.exception("history query failed request_id=%s", request_id)
        raise HTTPException(
            status_code=503,
            detail=f"history unavailable (request_id={request_id})",
        ) from exc
    return HistoryResponse(summary=summary, items=items)


async def _iterate_stream(
    stream: Any,
    request: Request,
    *,
    heartbeat_seconds: float,
    timeout_seconds: float,
) -> AsyncIterator[Any]:
    iterator = stream.__aiter__()
    pending: asyncio.Task[Any] | None = asyncio.create_task(iterator.__anext__())
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    try:
        while pending is not None:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise asyncio.TimeoutError
            done, _ = await asyncio.wait(
                {pending},
                timeout=min(heartbeat_seconds, remaining),
            )
            if not done:
                if await request.is_disconnected():
                    raise ClientDisconnected
                yield _HEARTBEAT
                continue
            try:
                chunk = pending.result()
            except StopAsyncIteration:
                pending = None
                break
            pending = None
            yield chunk
            pending = asyncio.create_task(iterator.__anext__())
    finally:
        if pending is not None and not pending.done():
            pending.cancel()
            with suppress(asyncio.CancelledError, StopAsyncIteration):
                await pending
        close = getattr(stream, "aclose", None)
        if callable(close):
            close_result = close()
            if inspect.isawaitable(close_result):
                with suppress(Exception):
                    await close_result


def _resolve_routing(req: ChatRequest, request: Request) -> RoutingInfo:
    if req.model:
        valid_groups = {m.id for m in BUILTIN_MODELS}
        if req.model not in valid_groups:
            raise HTTPException(
                status_code=400,
                detail=f"unknown model '{req.model}', valid: {sorted(valid_groups)}",
            )
        return RoutingInfo(target_group=req.model, forced=True)
    return request.app.state.difficulty.route(req.to_messages())


def _sse(obj: dict[str, Any]) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


def _completion_kwargs(routing: RoutingInfo, settings: Settings) -> dict[str, Any]:
    kwargs = copy.deepcopy(MODEL_COMPLETION_KWARGS.get(routing.target_group, {}))
    if routing.target_group == "glm-5.1" and routing.tier == Tier.REASONING.value:
        kwargs.pop("extra_body", None)
    kwargs["max_tokens"] = settings.max_output_tokens
    kwargs["timeout"] = settings.upstream_timeout_seconds
    return kwargs


async def _enforce_rate_limit(
    request: Request,
    key: str,
    limit: int,
) -> None:
    retry_after = await request.app.state.rate_limiter.check(key, limit)
    if retry_after:
        raise HTTPException(
            status_code=429,
            detail="rate limit exceeded",
            headers={"Retry-After": str(retry_after)},
        )


async def _record(
    request: Request,
    messages: list[dict[str, str]],
    result: ChatResponse,
) -> None:
    item = HistoryItem(
        ts=datetime.now().astimezone().isoformat(timespec="seconds"),
        query=_query_text(messages)[:1000],
        model=result.model,
        tier=result.routing.tier,
        forced=result.routing.forced,
        score=result.routing.score,
        usage=result.usage,
    )
    try:
        await asyncio.to_thread(request.app.state.history.append, item)
    except Exception:
        logger.exception("history write failed request_id=%s", _request_id(request))


def _query_text(messages: list[dict[str, str]]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            return message.get("content") or ""
    return ""


def _extract_content(resp: Any) -> str:
    choices = getattr(resp, "choices", None) or []
    if not choices:
        raise ValueError("upstream response has no choices")
    message = choices[0].message
    content = (getattr(message, "content", None) or "").strip()
    if content:
        return content
    return (getattr(message, "reasoning_content", None) or "").strip()


def _extract_usage(resp: Any) -> Usage:
    usage = getattr(resp, "usage", None)
    if usage is None:
        return _empty_usage()
    return _usage_from(usage)


def _empty_usage() -> Usage:
    return Usage(prompt_tokens=0, completion_tokens=0, total_tokens=0)


def _usage_from(usage: Any) -> Usage:
    return Usage(
        prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
        completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
        total_tokens=getattr(usage, "total_tokens", 0) or 0,
    )


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "unknown")


def _upstream_error(status_code: int, code: str, request_id: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "request_id": request_id},
    )

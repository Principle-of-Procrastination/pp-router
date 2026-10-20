"""Authenticated OpenAI endpoints backed by PP's existing routing engine."""

import asyncio
import hashlib
import hmac
import inspect
import json
import logging
from contextlib import aclosing, suppress
from typing import Any, AsyncIterator, Awaitable

import anyio
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import ValidationError
from starlette.requests import ClientDisconnect

from pprouter import api
from pprouter.config import BUILTIN_MODELS, Settings
from pprouter.openai_schemas import MAX_REQUEST_BYTES, CompletionRequest
from pprouter.schemas import ChatResponse, RoutingInfo, Usage
from pprouter.security import client_address


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1")
MODEL_IDS = ("auto", *(model.id for model in BUILTIN_MODELS))
RESPONSE_FIELDS = {"id", "object", "created", "model", "choices", "usage", "system_fingerprint"}
STREAM_CLOSE_TIMEOUT_SECONDS = 5.0


class _OwnedStream:
    """Close the upstream exactly once, including when ASGI never starts the body."""

    def __init__(self, stream: Any) -> None:
        self.stream = stream
        self.closed = False
        self._close_task: asyncio.Task[None] | None = None

    def __aiter__(self):
        return self.stream.__aiter__()

    async def aclose(self) -> None:
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close())
        # ASGI 2.3 disconnects cancel Starlette's AnyIO task group repeatedly at
        # checkpoints. Shield cleanup from that scope and from direct task.cancel().
        with anyio.CancelScope(shield=True):
            try:
                await asyncio.shield(self._close_task)
            except asyncio.CancelledError:
                await asyncio.shield(self._close_task)
                raise

    async def _close(self) -> None:
        with anyio.move_on_after(STREAM_CLOSE_TIMEOUT_SECONDS, shield=True) as scope:
            try:
                close = getattr(self.stream, "aclose", None)
                if callable(close):
                    result = close()
                    if inspect.isawaitable(result):
                        await result
            except Exception:
                logger.warning("OpenAI upstream stream cleanup failed")
        if scope.cancel_called:
            logger.warning("OpenAI upstream stream cleanup timed out")
        self.closed = True


class _CompletionStreamResponse(StreamingResponse):
    def __init__(self, events: AsyncIterator[str], stream: _OwnedStream, request: Request):
        super().__init__(
            events,
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache, no-store", "X-Accel-Buffering": "no"},
        )
        self.upstream = stream
        self.request = request

    async def __call__(self, scope, receive, send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            try:
                try:
                    await self.body_iterator.aclose()
                finally:
                    await self.upstream.aclose()
            finally:
                self.request.app.state.concurrency.release()


def _error(status: int, code: str, request: Request, headers=None) -> JSONResponse:
    return JSONResponse(
        {
            "error": {
                "message": code.replace("_", " "),
                "type": "invalid_request_error" if status < 500 else "server_error",
                "code": code,
                "request_id": api._request_id(request),
            }
        },
        status_code=status,
        headers=headers,
    )


def _authorize(request: Request) -> None:
    configured = request.app.state.settings.openai_api_key_hash
    if configured is None:
        raise HTTPException(503, "openai_api_disabled")
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    supplied = hashlib.sha256(token.encode()).digest()
    if scheme.lower() != "bearer" or not hmac.compare_digest(supplied, configured):
        raise HTTPException(401, "invalid_api_key", headers={"WWW-Authenticate": "Bearer"})


@router.get("/models")
async def models(request: Request) -> JSONResponse:
    try:
        _authorize(request)
        await api._enforce_rate_limit(
            request,
            f"read:{client_address(request)}",
            request.app.state.settings.read_requests_per_minute,
        )
    except HTTPException as exc:
        return _error(exc.status_code, str(exc.detail), request, exc.headers)
    return JSONResponse(
        {
            "object": "list",
            "data": [
                {"id": model, "object": "model", "created": 0, "owned_by": "pp-router"}
                for model in MODEL_IDS
            ],
        }
    )


async def _read_request(request: Request) -> CompletionRequest:
    if request.headers.get("content-type", "").split(";", 1)[0].strip() != "application/json":
        raise HTTPException(415, "expected_application_json")
    if request.headers.get("content-encoding", "identity").lower() != "identity":
        raise HTTPException(415, "unsupported_content_encoding")
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > MAX_REQUEST_BYTES:
            raise HTTPException(413, "request_too_large")
        data.extend(chunk)
    # Do not return Pydantic's input-bearing errors: messages and tool results are private.
    return CompletionRequest.model_validate_json(data)


def _routing(req: CompletionRequest, request: Request) -> RoutingInfo:
    if req.model == "auto":
        return request.app.state.difficulty.route(req.routing_messages())
    if req.model not in MODEL_IDS:
        raise HTTPException(400, "unknown_model")
    return RoutingInfo(target_group=req.model, forced=True)


def _kwargs(req: CompletionRequest, routing: RoutingInfo, settings: Settings) -> dict[str, Any]:
    kwargs = api._completion_kwargs(routing, settings)
    kwargs.update(
        req.model_dump(
            by_alias=True,
            exclude_none=True,
            exclude={
                "model", "messages", "max_tokens", "max_completion_tokens", "stream_options", "store"
            },
        )
    )
    requested_cap = req.max_tokens or req.max_completion_tokens or settings.max_output_tokens
    kwargs["max_tokens"] = min(requested_cap, settings.max_output_tokens)
    if req.stream:
        # Always request usage for PP accounting, even if the client does not want usage chunks.
        kwargs["stream_options"] = {"include_usage": True}
    return kwargs


async def _wait_upstream(awaitable: Awaitable[Any], request: Request, deadline: float) -> Any:
    pending = asyncio.ensure_future(awaitable)
    try:
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise asyncio.TimeoutError
            done, _ = await asyncio.wait({pending}, timeout=min(0.25, remaining))
            if done:
                return pending.result()
            if await request.is_disconnected():
                raise api.ClientDisconnected
    finally:
        if not pending.done():
            pending.cancel()
            with suppress(asyncio.CancelledError):
                await pending


def _payload(response: Any, *, streaming: bool) -> dict[str, Any]:
    raw = response if isinstance(response, dict) else response.model_dump(mode="json")
    if not isinstance(raw, dict) or raw.get("error") or not isinstance(raw.get("choices"), list):
        raise ValueError("invalid upstream completion")
    expected = "chat.completion.chunk" if streaming else "chat.completion"
    if raw.get("object") != expected or not isinstance(raw.get("id"), str):
        raise ValueError("invalid upstream completion metadata")
    if not streaming and not raw["choices"]:
        raise ValueError("upstream completion has no choices")
    for choice in raw["choices"]:
        message_key = "delta" if streaming else "message"
        if not isinstance(choice, dict) or not isinstance(choice.get(message_key), dict):
            raise ValueError("invalid upstream completion choice")
    # LiteLLM objects can also contain internal routing fields. Return the protocol fields only.
    return {key: value for key, value in raw.items() if key in RESPONSE_FIELDS}


def _usage(payload: dict[str, Any]) -> Usage:
    raw = payload.get("usage") or {}
    if not isinstance(raw, dict):
        raise ValueError("invalid upstream usage")
    values = {name: raw.get(name) or 0 for name in Usage.model_fields}
    if any(type(value) is not int or value < 0 for value in values.values()):
        raise ValueError("invalid upstream usage")
    return Usage(**values)


async def _record_usage(request: Request, routing: RoutingInfo, model: str, usage: Usage) -> None:
    # Code prompts, tool arguments, and tool outputs never enter the history store.
    # Existing public history still exposes aggregate model/tier/token metadata.
    await api._record(
        request,
        [],
        ChatResponse(content="", model=model, routing=routing, usage=usage),
    )


async def _events(
    stream: Any,
    req: CompletionRequest,
    request: Request,
    routing: RoutingInfo,
    deadline: float,
) -> AsyncIterator[str]:
    settings: Settings = request.app.state.settings
    usage = api._empty_usage()
    model = routing.target_group
    complete = False
    try:
        iterator = api._iterate_stream(
            stream,
            request,
            heartbeat_seconds=settings.stream_heartbeat_seconds,
            timeout_seconds=max(0, deadline - asyncio.get_running_loop().time()),
        )
        async with aclosing(iterator):
            async for chunk in iterator:
                if chunk is api._HEARTBEAT:
                    yield ": ping\n\n"
                    continue
                payload = _payload(chunk, streaming=True)
                model = payload.get("model") or model
                if payload.get("usage") is not None:
                    usage = _usage(payload)
                if not (req.stream_options and req.stream_options.include_usage):
                    payload.pop("usage", None)
                    if not payload["choices"]:
                        continue
                yield api._sse(payload)
        complete = True
    except (api.ClientDisconnected, ClientDisconnect):
        return
    except asyncio.TimeoutError:
        logger.warning("OpenAI stream timeout request_id=%s", api._request_id(request))
        yield _stream_error("upstream_timeout", request)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.warning("OpenAI stream failed request_id=%s", api._request_id(request))
        yield _stream_error("upstream_error", request)
    finally:
        if complete or usage.total_tokens:
            await _record_usage(request, routing, model, usage)
    yield "data: [DONE]\n\n"


def _stream_error(code: str, request: Request) -> str:
    return api._sse(json.loads(_error(502, code, request).body))


@router.post("/chat/completions")
async def completions(request: Request):
    settings: Settings = request.app.state.settings
    try:
        _authorize(request)
        await api._enforce_chat_rate_limit(request, settings)
        req = await asyncio.wait_for(_read_request(request), timeout=30)
        routing = _routing(req, request)
        kwargs = _kwargs(req, routing, settings)
        if not await request.app.state.concurrency.acquire():
            raise HTTPException(429, "too_many_concurrent_requests", headers={"Retry-After": "1"})
    except HTTPException as exc:
        return _error(exc.status_code, str(exc.detail), request, exc.headers)
    except ValidationError:
        return _error(400, "invalid_request", request)
    except asyncio.TimeoutError:
        return _error(408, "request_timeout", request)
    except ClientDisconnect:
        return _error(499, "client_disconnected", request)

    handed_to_stream = False
    try:
        deadline = asyncio.get_running_loop().time() + settings.upstream_timeout_seconds
        response = await _wait_upstream(
            request.app.state.router.acompletion(
                model=routing.target_group, messages=req.to_messages(), **kwargs
            ),
            request,
            deadline,
        )
        if req.stream:
            if not hasattr(response, "__aiter__"):
                raise ValueError("upstream did not return a stream")
            stream = _OwnedStream(response)
            result = _CompletionStreamResponse(
                _events(stream, req, request, routing, deadline), stream, request,
            )
            handed_to_stream = True
            return result
        payload = _payload(response, streaming=False)
        await _record_usage(
            request, routing, payload.get("model") or routing.target_group, _usage(payload)
        )
        return JSONResponse(payload)
    except (api.ClientDisconnected, ClientDisconnect):
        return _error(499, "client_disconnected", request)
    except asyncio.TimeoutError:
        logger.warning("OpenAI upstream timeout request_id=%s", api._request_id(request))
        return _error(504, "upstream_timeout", request)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.warning("OpenAI upstream failed request_id=%s", api._request_id(request))
        return _error(502, "upstream_error", request)
    finally:
        if not handed_to_stream:
            request.app.state.concurrency.release()

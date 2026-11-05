import asyncio
import json
import time
import uuid

import anyio
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.exc import SQLAlchemyError

from pprouter.errors import GatewayError
from pprouter.providers import UpstreamFailure, payload_for
from pprouter.records import Records
from pprouter.routing import choose


def sse(data):
    return "data: " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n\n"


def tools_in(body):
    return [
        tool["id"]
        for c in body.get("choices", [])
        for tool in c.get("message", {}).get("tool_calls", [])
        if tool.get("id")
    ]


class MeteredStreamResponse(StreamingResponse):
    def __init__(self, *args, cleanup, **kwargs):
        super().__init__(*args, **kwargs)
        self.cleanup = cleanup

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            with anyio.CancelScope(shield=True):
                try:
                    await self.body_iterator.aclose()
                finally:
                    await self.cleanup()


class Gateway:
    def __init__(self, db, settings, providers, limits):
        self.db, self.settings, self.providers, self.limits = db, settings, providers, limits
        self.records = Records(db)

    async def handle(self, request, req, caller, trace_id=None, *, routing_only=False):
        # Starlette does not cancel a non-streaming handler when its client leaves.
        # Watch the ASGI disconnect until a response (or stream owner) is ready.
        async def disconnected():
            while (await request.receive())["type"] != "http.disconnect":
                pass

        operation = self.preview if routing_only else self.call
        work = asyncio.create_task(operation(req, caller, trace_id))
        watcher = asyncio.create_task(disconnected())
        try:
            done, _ = await asyncio.wait({work, watcher}, return_when=asyncio.FIRST_COMPLETED)
            if work in done:
                return work.result()
            work.cancel()
            await asyncio.gather(work, return_exceptions=True)
            raise GatewayError(499, "client_disconnected", "Client disconnected before response.")
        finally:
            watcher.cancel()
            if not work.done():
                work.cancel()
            with anyio.CancelScope(shield=True):
                await asyncio.gather(work, watcher, return_exceptions=True)

    async def preview(self, req, caller, trace_id=None):
        if req.model != "auto" or req.stream:
            raise GatewayError(
                400, "invalid_preview", "Routing preview requires auto and stream=false."
            )
        release = self.limits.acquire(caller)
        request_id = uuid.uuid4().hex
        started = False
        try:
            await self.records.start_request(caller, req, request_id, trace_id)
            started = True
            selected, _, _, info = await choose(self, req, caller, request_id)
            info.update(purpose="routing_preview", execution_skipped=True)
            await self.records.routing(request_id, info)
            # Selection is not execution: actual_model remains null on this root request.
            await self.records.finish_request(request_id, "succeeded")
            return JSONResponse(
                {"request_id": request_id, "selected_model": selected.id, "routing": info},
                headers={"X-Request-ID": request_id},
            )
        except BaseException as exc:
            status = "cancelled" if isinstance(exc, asyncio.CancelledError) else "failed"
            code = exc.code if isinstance(exc, GatewayError) else "preview_interrupted"
            if started:
                with anyio.CancelScope(shield=True):
                    await self.records.finish_request(request_id, status, error=code)
            if isinstance(exc, GatewayError):
                exc.request_id = request_id
            raise
        finally:
            release()

    async def call(self, req, caller, trace_id=None):
        release = self.limits.acquire(caller)
        request_id = uuid.uuid4().hex
        started = False
        active_attempt = None
        result = None
        upstream_stream = None
        selected = None
        try:
            await self.records.start_request(caller, req, request_id, trace_id)
            started = True
            selected, candidates, binding, info = await choose(self, req, caller, request_id)
            for ordinal in (1, 2):
                payload, mode = payload_for(
                    selected, req, caller, binding.mode if binding else None
                )
                active_attempt = await self.records.start_attempt(
                    request_id, ordinal, "completion", selected
                )
                begin = time.monotonic()
                try:
                    async with asyncio.timeout(self.settings.timeout_seconds):
                        if req.stream:
                            upstream_stream = await self.providers.stream(
                                selected, payload, self.settings.timeout_seconds
                            )
                            iterator = upstream_stream.__aiter__()
                            try:
                                first = await anext(iterator)
                            except StopAsyncIteration:
                                raise UpstreamFailure("empty_upstream_stream") from None

                            async def cleanup(
                                stream=upstream_stream, attempt=active_attempt, model=selected
                            ):
                                try:
                                    await stream.aclose()
                                    await self.records.finish_attempt(
                                        attempt,
                                        status="cancelled",
                                        error_code="client_disconnected",
                                    )
                                    await self.records.finish_request(
                                        request_id, "cancelled", model.id, "client_disconnected"
                                    )
                                finally:
                                    release()

                            response = MeteredStreamResponse(
                                self._stream(
                                    req,
                                    caller,
                                    selected,
                                    mode,
                                    request_id,
                                    active_attempt,
                                    upstream_stream,
                                    iterator,
                                    first,
                                    begin,
                                    release,
                                ),
                                cleanup=cleanup,
                                media_type="text/event-stream",
                                headers={
                                    "X-Request-ID": request_id,
                                    "Cache-Control": "no-cache",
                                    "X-Accel-Buffering": "no",
                                },
                            )
                            # Generator owns the connection and concurrency lease from here.
                            active_attempt = None
                            return response
                        result = await self.providers.complete(
                            selected, payload, self.settings.timeout_seconds
                        )
                    if not result.body.get("choices") or "message" not in result.body["choices"][0]:
                        raise UpstreamFailure("invalid_upstream_response")
                    if any(
                        c.get("finish_reason") in ("aborted", "insufficient_system_resource")
                        for c in result.body["choices"]
                    ):
                        raise UpstreamFailure("upstream_generation_aborted")
                    await self.records.finish_attempt(
                        active_attempt,
                        status="succeeded",
                        usage=result.body.get("usage"),
                        upstream_id=result.upstream_id,
                        reported_model=result.body.get("model"),
                        caller=caller,
                        tool_ids=tools_in(result.body),
                        mode=mode,
                    )
                    active_attempt = None
                    await self.records.finish_request(request_id, "succeeded", selected.id)
                    body = dict(result.body)
                    body.update(id="chatcmpl-" + request_id, model=selected.id)
                    return JSONResponse(body, headers={"X-Request-ID": request_id})
                except TimeoutError:
                    raise UpstreamFailure("upstream_timeout", 504) from None
                except UpstreamFailure as exc:
                    if upstream_stream:
                        await upstream_stream.aclose()
                        upstream_stream = None
                    await self.records.finish_attempt(
                        active_attempt,
                        status="failed",
                        error_code=exc.code,
                        upstream_id=exc.upstream_id,
                        usage=result.body.get("usage") if result else None,
                    )
                    active_attempt = None
                    if ordinal == 2 or not exc.retryable:
                        raise
                    if req.model == "auto" and not binding:
                        order = caller.grant.policy.get("fallback_order", [])
                        selected = next(
                            (
                                m
                                for name in order
                                for m in candidates
                                if m.id == name and m.id != selected.id
                            ),
                            selected,
                        )
                    info.update(execution_retry=True, actual_model=selected.id)
                    await self.records.routing(request_id, info)
        except BaseException as exc:
            code = (
                exc.code
                if isinstance(exc, (UpstreamFailure, GatewayError))
                else "request_interrupted"
            )
            status = "cancelled" if isinstance(exc, asyncio.CancelledError) else "failed"
            with anyio.CancelScope(shield=True):
                if upstream_stream:
                    await upstream_stream.aclose()
                if active_attempt:
                    await self.records.finish_attempt(
                        active_attempt,
                        status=status,
                        error_code=code,
                        usage=result.body.get("usage") if result else None,
                        upstream_id=result.upstream_id if result else None,
                    )
                if started:
                    await self.records.finish_request(
                        request_id, status, selected.id if selected else None, code
                    )
            if isinstance(exc, UpstreamFailure):
                error = GatewayError(
                    exc.status,
                    exc.code,
                    "Upstream call failed. See the request record for diagnostics.",
                )
                error.request_id = request_id
                raise error from None
            if isinstance(exc, GatewayError):
                exc.request_id = request_id
            raise
        finally:
            if not req.stream or upstream_stream is None or active_attempt is not None:
                release()

    async def _stream(
        self,
        req,
        caller,
        model,
        mode,
        request_id,
        attempt_id,
        upstream,
        iterator,
        first,
        begin,
        release,
    ):
        usage, reported_model = None, None
        tool_ids, finish_seen = set(), False
        terminal_error = False
        first_token_ms = None
        pending = None
        final_recorded = False
        status, error = "cancelled", "client_disconnected"
        deadline = begin + self.settings.timeout_seconds
        try:
            chunk = first
            while True:
                if chunk.get("usage") is not None:
                    usage = chunk["usage"]
                reported_model = chunk.get("model", reported_model)
                choices = chunk.get("choices", [])
                for choice in choices:
                    delta = choice.get("delta", {})
                    if first_token_ms is None and (
                        delta.get("content")
                        or delta.get("tool_calls")
                        or delta.get("reasoning_content")
                    ):
                        first_token_ms = (time.monotonic() - begin) * 1000
                    for tool in delta.get("tool_calls", []):
                        if tool.get("id"):
                            tool_ids.add(tool["id"])
                    if choice.get("finish_reason"):
                        finish_seen = True
                        if choice["finish_reason"] in ("aborted", "insufficient_system_resource"):
                            terminal_error = True
                if choices:
                    body = {k: v for k, v in chunk.items() if k != "usage"}
                    body.update(id="chatcmpl-" + request_id, model=model.id)
                    yield sse(body)
                pending = asyncio.create_task(anext(iterator))
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise UpstreamFailure("upstream_timeout", 504)
                    done, _ = await asyncio.wait({pending}, timeout=min(15, remaining))
                    if done:
                        break
                    yield ": heartbeat\n\n"
                try:
                    chunk = pending.result()
                except StopAsyncIteration:
                    break
                finally:
                    pending = None
            if terminal_error:
                raise UpstreamFailure("upstream_generation_aborted")
            if not finish_seen:
                raise UpstreamFailure("incomplete_upstream_stream")
            status, error = "succeeded", None
            await self.records.finish_attempt(
                attempt_id,
                status=status,
                usage=usage,
                upstream_id=upstream.upstream_id,
                reported_model=reported_model,
                first_token_ms=first_token_ms,
                caller=caller,
                tool_ids=tool_ids,
                mode=mode,
            )
            await self.records.finish_request(request_id, status, model.id)
            final_recorded = True
            if req.stream_options and req.stream_options.include_usage and usage is not None:
                yield sse(
                    {
                        "id": "chatcmpl-" + request_id,
                        "object": "chat.completion.chunk",
                        "created": int(time.time()),
                        "model": model.id,
                        "choices": [],
                        "usage": usage,
                    }
                )
            yield "data: [DONE]\n\n"
        except (UpstreamFailure, TimeoutError) as exc:
            status, error = (
                "failed",
                exc.code if isinstance(exc, UpstreamFailure) else "upstream_timeout",
            )
            yield sse(
                GatewayError(502, error, "Upstream stream was interrupted.").payload(request_id)
            )
        except Exception as exc:
            status = "failed"
            error = (
                "storage_unavailable"
                if isinstance(exc, SQLAlchemyError)
                else "invalid_upstream_stream"
            )
            yield sse(
                GatewayError(502, error, "Stream could not be completed.").payload(request_id)
            )
        finally:
            with anyio.CancelScope(shield=True):
                try:
                    if pending:
                        pending.cancel()
                        await asyncio.gather(pending, return_exceptions=True)
                    await upstream.aclose()
                    if not final_recorded:
                        await self.records.finish_attempt(
                            attempt_id,
                            status=status,
                            error_code=error,
                            usage=usage,
                            upstream_id=upstream.upstream_id,
                            reported_model=reported_model,
                            first_token_ms=first_token_ms,
                        )
                        await self.records.finish_request(request_id, status, model.id, error)
                finally:
                    release()

import asyncio
import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from pprouter.config import BUILTIN_MODELS
from pprouter.schemas import (
    ChatRequest,
    ChatResponse,
    HistoryItem,
    HistoryResponse,
    HistorySummary,
    ModelInfo,
    ModelStat,
    RoutingInfo,
    Usage,
)

router = APIRouter()


@router.get("/models")
def list_models() -> list[ModelInfo]:
    return [
        ModelInfo(id=m.id, litellm_model=m.litellm_model, tiers=[t.value for t in m.tiers])
        for m in BUILTIN_MODELS
    ]


@router.post("/chat")
async def chat(req: ChatRequest, request: Request) -> ChatResponse:
    engine = request.app.state.router
    messages = req.to_messages()
    routing = _resolve_routing(req, request)

    try:
        resp = await engine.acompletion(model=routing.target_group, messages=messages)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"upstream error: {e}") from e

    result = ChatResponse(
        content=_extract_content(resp),
        model=getattr(resp, "model", None) or routing.target_group,
        routing=routing,
        usage=_extract_usage(resp),
    )
    await _record(request, messages, result)
    return result


@router.post("/chat/stream")
async def chat_stream(req: ChatRequest, request: Request) -> StreamingResponse:
    engine = request.app.state.router
    messages = req.to_messages()
    routing = _resolve_routing(req, request)

    async def events() -> Any:
        yield _sse({"type": "routing", "routing": routing.model_dump()})
        parts: list[str] = []
        usage = Usage(prompt_tokens=0, completion_tokens=0, total_tokens=0)
        model_used = routing.target_group
        try:
            stream = await engine.acompletion(
                model=routing.target_group,
                messages=messages,
                stream=True,
                stream_options={"include_usage": True},
            )
            it = stream.__aiter__()
            while True:
                try:
                    chunk = await asyncio.wait_for(it.__anext__(), timeout=15)
                except StopAsyncIteration:
                    break
                except asyncio.TimeoutError:
                    yield ": ping\n\n"  # 心跳：上游静默时保活，避免网关空闲超时
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
        except Exception as e:
            yield _sse({"type": "error", "detail": f"upstream error: {e}"})
            return

        yield _sse(
            {
                "type": "done",
                "model": model_used,
                "routing": routing.model_dump(),
                "usage": usage.model_dump(),
            }
        )
        result = ChatResponse(
            content="".join(parts).strip(),
            model=model_used,
            routing=routing,
            usage=usage,
        )
        await _record(request, messages, result)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 关键：禁用 nginx 网关缓冲，SSE 即时下发
        },
    )


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


@router.get("/history")
def history(request: Request, limit: int = 50) -> HistoryResponse:
    records = request.app.state.history.read_all()

    total_tokens = 0
    by_model: dict[str, ModelStat] = {}
    for r in records:
        total_tokens += r.usage.total_tokens
        prev = by_model.get(r.model)
        if prev is None:
            by_model[r.model] = ModelStat(requests=1, total_tokens=r.usage.total_tokens)
        else:
            by_model[r.model] = ModelStat(
                requests=prev.requests + 1,
                total_tokens=prev.total_tokens + r.usage.total_tokens,
            )

    return HistoryResponse(
        summary=HistorySummary(
            total_requests=len(records),
            total_tokens=total_tokens,
            by_model=by_model,
        ),
        items=list(reversed(records))[:limit],
    )


async def _record(
    request: Request, messages: list[dict[str, str]], result: ChatResponse
) -> None:
    item = HistoryItem(
        ts=datetime.now().astimezone().isoformat(timespec="seconds"),
        query=_query_text(messages),
        model=result.model,
        tier=result.routing.tier,
        forced=result.routing.forced,
        score=result.routing.score,
        usage=result.usage,
    )
    try:
        await asyncio.to_thread(request.app.state.history.append, item)
    except Exception:
        pass  # 记账失败不应阻断对话返回


def _query_text(messages: list[dict[str, str]]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            return message.get("content") or ""
    return ""


def _extract_content(resp: Any) -> str:
    message = resp.choices[0].message
    content = (message.content or "").strip()
    if content:
        return content
    return (getattr(message, "reasoning_content", None) or "").strip()


def _extract_usage(resp: Any) -> Usage:
    usage = getattr(resp, "usage", None)
    if usage is None:
        return Usage(prompt_tokens=0, completion_tokens=0, total_tokens=0)
    return _usage_from(usage)


def _usage_from(usage: Any) -> Usage:
    return Usage(
        prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
        completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
        total_tokens=getattr(usage, "total_tokens", 0) or 0,
    )

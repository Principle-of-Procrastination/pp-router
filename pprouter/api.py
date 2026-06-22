import asyncio
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request

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
    difficulty = request.app.state.difficulty
    valid_groups = {m.id for m in BUILTIN_MODELS}

    messages = req.to_messages()

    if req.model:
        if req.model not in valid_groups:
            raise HTTPException(
                status_code=400,
                detail=f"unknown model '{req.model}', valid: {sorted(valid_groups)}",
            )
        routing = RoutingInfo(target_group=req.model, forced=True)
    else:
        routing = difficulty.route(messages)

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
    return Usage(
        prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
        completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
        total_tokens=getattr(usage, "total_tokens", 0) or 0,
    )

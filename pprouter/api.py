from typing import Any

from fastapi import APIRouter, HTTPException, Request

from pprouter.config import BUILTIN_MODELS
from pprouter.schemas import ChatRequest, ChatResponse, ModelInfo, RoutingInfo, Usage

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

    return ChatResponse(
        content=_extract_content(resp),
        model=getattr(resp, "model", None) or routing.target_group,
        routing=routing,
        usage=_extract_usage(resp),
    )


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

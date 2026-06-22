from typing import Literal, Optional

from pydantic import BaseModel, model_validator


class Message(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    query: Optional[str] = None
    messages: Optional[list[Message]] = None
    model: Optional[str] = None

    @model_validator(mode="after")
    def _require_input(self) -> "ChatRequest":
        if not self.query and not self.messages:
            raise ValueError("either 'query' or 'messages' is required")
        return self

    def to_messages(self) -> list[dict[str, str]]:
        if self.messages:
            return [{"role": m.role, "content": m.content} for m in self.messages]
        return [{"role": "user", "content": self.query or ""}]


class Usage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class RoutingInfo(BaseModel):
    target_group: str
    forced: bool = False
    tier: Optional[str] = None
    score: Optional[float] = None


class ChatResponse(BaseModel):
    content: str
    model: str
    routing: RoutingInfo
    usage: Usage


class ModelInfo(BaseModel):
    id: str
    litellm_model: str
    tiers: list[str]


class HistoryItem(BaseModel):
    ts: str
    query: str
    model: str
    tier: Optional[str] = None
    forced: bool = False
    score: Optional[float] = None
    usage: Usage


class ModelStat(BaseModel):
    requests: int
    total_tokens: int


class HistorySummary(BaseModel):
    total_requests: int
    total_tokens: int
    by_model: dict[str, ModelStat]


class HistoryResponse(BaseModel):
    summary: HistorySummary
    items: list[HistoryItem]

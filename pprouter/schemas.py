from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator


MAX_MESSAGE_CHARS = 20_000
MAX_TOTAL_MESSAGE_CHARS = 60_000
MAX_MESSAGES = 40


class Message(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)


class ChatRequest(BaseModel):
    query: Optional[str] = Field(default=None, min_length=1, max_length=MAX_MESSAGE_CHARS)
    messages: Optional[list[Message]] = Field(
        default=None, min_length=1, max_length=MAX_MESSAGES
    )
    model: Optional[str] = Field(default=None, min_length=1, max_length=64)

    @model_validator(mode="after")
    def _require_input(self) -> "ChatRequest":
        if (self.query is None) == (self.messages is None):
            raise ValueError("exactly one of 'query' or 'messages' is required")
        if self.query is not None and not self.query.strip():
            raise ValueError("'query' cannot be blank")
        if self.messages is not None:
            if not any(message.role == "user" for message in self.messages):
                raise ValueError("'messages' must contain at least one user message")
            total_chars = sum(len(message.content) for message in self.messages)
            if total_chars > MAX_TOTAL_MESSAGE_CHARS:
                raise ValueError(
                    f"total message content cannot exceed {MAX_TOTAL_MESSAGE_CHARS} characters"
                )
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


class SessionRequest(BaseModel):
    access_key: str = Field(min_length=1, max_length=512)


class SessionResponse(BaseModel):
    token: str
    expires_at: int


class SessionStatus(BaseModel):
    authenticated: bool
    expires_at: int


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"

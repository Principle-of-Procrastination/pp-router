"""Bounded, text-and-function-tool subset of the OpenAI chat protocol."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


MAX_REQUEST_BYTES = 1_048_576
MAX_TEXT_CHARS = 262_144


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class TextPart(StrictModel):
    type: Literal["text"]
    text: str = Field(max_length=MAX_TEXT_CHARS)


class FunctionCall(StrictModel):
    name: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    arguments: str = Field(max_length=MAX_TEXT_CHARS)


class ToolCall(StrictModel):
    id: str = Field(min_length=1, max_length=256)
    type: Literal["function"]
    function: FunctionCall


class ChatMessage(StrictModel):
    role: Literal["developer", "system", "user", "assistant", "tool"]
    content: str | list[TextPart] | None = Field(default=None, max_length=MAX_TEXT_CHARS)
    name: str | None = Field(default=None, min_length=1, max_length=64)
    tool_calls: list[ToolCall] | None = Field(default=None, min_length=1, max_length=128)
    tool_call_id: str | None = Field(default=None, min_length=1, max_length=256)
    reasoning_content: str | None = Field(default=None, max_length=MAX_TEXT_CHARS)

    @model_validator(mode="after")
    def validate_role_fields(self) -> "ChatMessage":
        if self.role != "assistant" and self.tool_calls is not None:
            raise ValueError("tool_calls requires the assistant role")
        if self.role != "assistant" and self.reasoning_content is not None:
            raise ValueError("reasoning_content requires the assistant role")
        if self.role == "tool":
            if self.tool_call_id is None or self.content is None:
                raise ValueError("tool messages require tool_call_id and text content")
        elif self.tool_call_id is not None:
            raise ValueError("tool_call_id requires the tool role")
        if self.content is None and not self.tool_calls:
            raise ValueError("messages require text content or assistant tool_calls")
        return self

    def text(self) -> str:
        if isinstance(self.content, str):
            return self.content
        return "\n".join(part.text for part in self.content or [])


class ToolFunction(StrictModel):
    name: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    description: str | None = Field(default=None, max_length=MAX_TEXT_CHARS)
    parameters: dict[str, Any] | None = None
    strict: bool | None = None


class ToolDefinition(StrictModel):
    type: Literal["function"]
    function: ToolFunction


class SelectedFunction(StrictModel):
    name: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")


class SelectedTool(StrictModel):
    type: Literal["function"]
    function: SelectedFunction


class StreamOptions(StrictModel):
    include_usage: bool = False


class JsonSchemaFormat(StrictModel):
    name: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    description: str | None = Field(default=None, max_length=MAX_TEXT_CHARS)
    schema_: dict[str, Any] = Field(alias="schema")
    strict: bool | None = None


class ResponseFormat(StrictModel):
    type: Literal["text", "json_object", "json_schema"]
    json_schema: JsonSchemaFormat | None = None

    @model_validator(mode="after")
    def validate_schema(self) -> "ResponseFormat":
        if (self.type == "json_schema") != (self.json_schema is not None):
            raise ValueError("json_schema is required only for the json_schema response format")
        return self


class CompletionRequest(StrictModel):
    model: str = Field(min_length=1, max_length=64)
    messages: list[ChatMessage] = Field(min_length=1, max_length=512)
    stream: bool = False
    store: bool = False
    stream_options: StreamOptions | None = None
    max_tokens: int | None = Field(default=None, ge=1, le=1_000_000)
    max_completion_tokens: int | None = Field(default=None, ge=1, le=1_000_000)
    temperature: float | None = Field(default=None, ge=0, le=2)
    top_p: float | None = Field(default=None, ge=0, le=1)
    frequency_penalty: float | None = Field(default=None, ge=-2, le=2)
    presence_penalty: float | None = Field(default=None, ge=-2, le=2)
    seed: int | None = None
    user: str | None = Field(default=None, min_length=1, max_length=256)
    n: Literal[1] = 1
    stop: str | list[str] | None = None
    tools: list[ToolDefinition] | None = Field(default=None, max_length=128)
    tool_choice: Literal["none", "auto", "required"] | SelectedTool | None = None
    parallel_tool_calls: bool | None = None
    response_format: ResponseFormat | None = None

    @model_validator(mode="after")
    def validate_options(self) -> "CompletionRequest":
        if self.store:
            raise ValueError("stored completions are not supported")
        if self.max_tokens is not None and self.max_completion_tokens is not None:
            raise ValueError("provide only one output token limit")
        if self.stream_options is not None and not self.stream:
            raise ValueError("stream_options requires streaming")
        if not any(message.role == "user" for message in self.messages):
            raise ValueError("messages must contain a user message")
        if isinstance(self.stop, list) and (
            not 1 <= len(self.stop) <= 4 or any(len(item) > 4096 for item in self.stop)
        ):
            raise ValueError("stop must contain 1–4 strings of at most 4096 characters")
        if isinstance(self.stop, str) and len(self.stop) > 4096:
            raise ValueError("stop must contain at most 4096 characters")
        names = [tool.function.name for tool in self.tools or []]
        if len(set(names)) != len(names):
            raise ValueError("tool names must be unique")
        if isinstance(self.tool_choice, SelectedTool) and self.tool_choice.function.name not in names:
            raise ValueError("selected tool must be present in tools")
        if self.tool_choice == "required" and not self.tools:
            raise ValueError("required tool choice requires tools")
        return self

    def to_messages(self) -> list[dict[str, Any]]:
        return [message.model_dump(exclude_unset=True) for message in self.messages]

    def routing_messages(self) -> list[dict[str, str]]:
        # The original classifier consumes text. Do not feed tool results into it,
        # and preserve all original roles/content in the separate provider request.
        return [
            {
                "role": "system" if message.role == "developer" else message.role,
                "content": message.text(),
            }
            for message in self.messages
            if message.role in {"system", "developer", "user"}
        ]

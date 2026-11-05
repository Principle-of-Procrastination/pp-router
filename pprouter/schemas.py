import base64
import binascii
import ipaddress
import json
from typing import Annotated, Literal
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TextPart(StrictModel):
    type: Literal["text"]
    text: str


class ImageURL(StrictModel):
    url: str
    detail: Literal["auto", "low", "high", "original"] = "auto"

    @model_validator(mode="after")
    def valid_url(self):
        if self.url.startswith("data:"):
            header, sep, data = self.url.partition(",")
            if (
                header
                not in {
                    "data:image/png;base64",
                    "data:image/jpeg;base64",
                    "data:image/webp;base64",
                    "data:image/gif;base64",
                }
                or not sep
            ):
                raise ValueError("Use a supported base64 image data URL")
            if len(data) > 7 * 1024 * 1024:
                raise ValueError("Inline image exceeds 5 MiB")
            try:
                decoded = base64.b64decode(data, validate=True)
            except (ValueError, binascii.Error) as exc:
                raise ValueError("Invalid base64 image") from exc
            if not decoded or len(decoded) > 5 * 1024 * 1024:
                raise ValueError("Inline image must be between 1 byte and 5 MiB")
        else:
            try:
                parsed = urlsplit(self.url)
                if (
                    len(self.url) > 8192
                    or parsed.scheme != "https"
                    or not parsed.hostname
                    or parsed.username
                    or parsed.password
                ):
                    raise ValueError("Images require an HTTPS URL without credentials")
                host = parsed.hostname.lower()
                if host == "localhost" or host.endswith((".localhost", ".local")):
                    raise ValueError("Local image URLs are not allowed")
                try:
                    address = ipaddress.ip_address(host)
                except ValueError:
                    address = None
                if address and not address.is_global:
                    raise ValueError("Private image URLs are not allowed")
            except ValueError as exc:
                raise ValueError("Invalid or private image URL") from exc
        return self


class ImagePart(StrictModel):
    type: Literal["image_url"]
    image_url: ImageURL


ContentPart = Annotated[TextPart | ImagePart, Field(discriminator="type")]


class FunctionCall(StrictModel):
    name: str = Field(min_length=1, max_length=128)
    arguments: str


class ToolCall(StrictModel):
    id: str = Field(min_length=1, max_length=256)
    # DeepSeek may also return a stream-style index in a non-streaming message.
    # Accept SDK round trips, but omit this response-only position upstream.
    index: int | None = Field(default=None, ge=0, le=63, exclude=True)
    type: Literal["function"] = "function"
    function: FunctionCall


class Message(StrictModel):
    role: Literal["system", "developer", "user", "assistant", "tool"]
    content: str | list[ContentPart] | None = None
    name: str | None = Field(default=None, max_length=128)
    reasoning_content: str | None = None
    # Nullable SDK response fields are accepted for message.model_dump() round trips.
    refusal: str | None = None
    annotations: list[dict] | None = None
    audio: None = None
    function_call: None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = Field(default=None, max_length=256)

    @model_validator(mode="after")
    def validate_role(self):
        if self.role == "tool" and not self.tool_call_id:
            raise ValueError("Tool messages require tool_call_id")
        if self.role != "tool" and self.tool_call_id is not None:
            raise ValueError("tool_call_id is only valid on tool messages")
        if self.role != "assistant" and (
            self.tool_calls is not None
            or self.reasoning_content is not None
            or self.refusal is not None
            or self.annotations is not None
        ):
            raise ValueError("Only assistant messages may contain reasoning or tool calls")
        if self.content is None and not (self.role == "assistant" and self.tool_calls):
            raise ValueError("Message content is required")
        if isinstance(self.content, list) and (
            not self.content or self.role not in ("user", "tool")
        ):
            raise ValueError("Content arrays are supported on user and tool messages")
        return self


class FunctionSpec(StrictModel):
    name: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,128}$")
    description: str | None = Field(default=None, max_length=4000)
    parameters: dict = Field(default_factory=lambda: {"type": "object", "properties": {}})
    strict: bool | None = None

    @model_validator(mode="after")
    def check_schema(self):
        try:
            Draft202012Validator.check_schema(self.parameters)
        except SchemaError as exc:
            raise ValueError("Invalid tool JSON schema") from exc
        return self


class ToolSpec(StrictModel):
    type: Literal["function"]
    function: FunctionSpec


class NamedFunction(StrictModel):
    name: str


class NamedChoice(StrictModel):
    type: Literal["function"]
    function: NamedFunction


class JSONSchema(StrictModel):
    name: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    schema_: dict = Field(alias="schema")
    strict: bool = True
    description: str | None = None

    @model_validator(mode="after")
    def check_schema(self):
        try:
            Draft202012Validator.check_schema(self.schema_)
        except SchemaError as exc:
            raise ValueError("Invalid output JSON schema") from exc
        return self


class ResponseFormat(StrictModel):
    type: Literal["text", "json_object", "json_schema"]
    json_schema: JSONSchema | None = None

    @model_validator(mode="after")
    def check_type(self):
        if (self.type == "json_schema") != (self.json_schema is not None):
            raise ValueError("json_schema must be supplied only for json_schema format")
        return self


class StreamOptions(StrictModel):
    include_usage: bool = False


class Thinking(StrictModel):
    type: Literal["enabled", "disabled"]


class ChatRequest(StrictModel):
    model: str = Field(min_length=1, max_length=128)
    messages: list[Message] = Field(min_length=1, max_length=200)
    stream: bool = False
    stream_options: StreamOptions | None = None
    n: Literal[1] = 1
    temperature: float | None = Field(default=None, ge=0, le=2)
    top_p: float | None = Field(default=None, gt=0, le=1)
    max_tokens: int | None = Field(default=None, ge=1, le=32768)
    max_completion_tokens: int | None = Field(default=None, ge=1, le=32768)
    tools: list[ToolSpec] | None = Field(default=None, min_length=1, max_length=64)
    tool_choice: Literal["auto", "none", "required"] | NamedChoice | None = None
    response_format: ResponseFormat | None = None
    reasoning_effort: Literal["none", "minimal", "low", "medium", "high", "xhigh", "max"] | None = (
        None
    )
    thinking: Thinking | None = None
    stop: str | list[str] | None = None
    user: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def validate_request(self):
        if self.max_tokens and self.max_completion_tokens:
            raise ValueError("Specify only one output token limit")
        if self.stream_options and not self.stream:
            raise ValueError("stream_options requires stream=true")
        images = sum(
            isinstance(p, ImagePart)
            for m in self.messages
            if isinstance(m.content, list)
            for p in m.content
        )
        if images > 8:
            raise ValueError("At most 8 images are allowed")
        if self.tool_choice not in (None, "none") and not self.tools:
            raise ValueError("tool_choice requires tools")
        names = [t.function.name for t in self.tools or []]
        if len(names) != len(set(names)):
            raise ValueError("Tool names must be unique")
        if (
            isinstance(self.tool_choice, NamedChoice)
            and self.tool_choice.function.name not in names
        ):
            raise ValueError("Named tool must be present in tools")
        if isinstance(self.stop, list) and (not 1 <= len(self.stop) <= 16):
            raise ValueError("Provide between 1 and 16 stop sequences")
        return self

    @property
    def has_images(self):
        return any(
            isinstance(p, ImagePart)
            for m in self.messages
            if isinstance(m.content, list)
            for p in m.content
        )

    def payload(self) -> dict:
        result = self.model_dump(
            exclude_none=True,
            by_alias=True,
            exclude={"model", "stream", "stream_options", "n", "user"},
        )
        # Preserve null assistant content in tool-call messages.
        for original, output in zip(self.messages, result["messages"]):
            if original.content is None:
                output["content"] = None
            if output["role"] == "developer":
                output["role"] = "system"
        return result

    def text_bound(self) -> int:
        # Conservative byte bound for text; image counts are protective estimates only.
        text = "".join(
            m.content
            if isinstance(m.content, str)
            else "".join(p.text for p in m.content or [] if isinstance(p, TextPart))
            for m in self.messages
        )
        text += "".join(m.reasoning_content or "" for m in self.messages)
        text += json.dumps([t.model_dump() for t in self.tools or []], ensure_ascii=False)
        text += json.dumps([t.model_dump() for m in self.messages for t in m.tool_calls or []])
        text += json.dumps(
            self.response_format.model_dump(by_alias=True) if self.response_format else {}
        )
        image_count = sum(
            isinstance(p, ImagePart)
            for m in self.messages
            if isinstance(m.content, list)
            for p in m.content
        )
        return len(text.encode()) + 16 * len(self.messages) + 80_000 * image_count

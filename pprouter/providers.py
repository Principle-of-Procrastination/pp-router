from dataclasses import dataclass
from typing import AsyncIterator

import httpx
import openai
from openai import AsyncOpenAI

from pprouter.errors import GatewayError
from pprouter.schemas import ChatRequest, NamedChoice


@dataclass
class UpstreamFailure(Exception):
    code: str
    status: int = 502
    retryable: bool = False
    upstream_id: str | None = None


@dataclass
class Result:
    body: dict
    upstream_id: str | None = None


class Stream:
    def __init__(self, stream, upstream_id=None):
        self.source = stream
        self.upstream_id = upstream_id

    def __aiter__(self) -> AsyncIterator[dict]:
        return self._iterate()

    async def _iterate(self):
        try:
            async for chunk in self.source:
                yield chunk.model_dump(mode="json", exclude_none=True)
        except openai.APIError as exc:
            raise convert_error(exc) from None

    async def aclose(self):
        await self.source.close()


def convert_error(exc: openai.APIError) -> UpstreamFailure:
    request_id = getattr(exc, "request_id", None)
    if isinstance(exc, openai.RateLimitError):
        return UpstreamFailure("upstream_rate_limit", 429, True, request_id)
    if isinstance(exc, openai.APITimeoutError):
        return UpstreamFailure("upstream_timeout", 504, False, request_id)
    if isinstance(exc, openai.APIConnectionError):
        safe = isinstance(exc.__cause__, (httpx.ConnectError, httpx.ConnectTimeout))
        return UpstreamFailure("upstream_connection_error", 502, safe, request_id)
    if isinstance(exc, openai.APIStatusError):
        code = "upstream_rejected_request" if exc.status_code == 400 else "upstream_error"
        if exc.status_code in (401, 403):
            code = "upstream_credentials_rejected"
        return UpstreamFailure(code, 502, False, request_id)
    return UpstreamFailure("upstream_error", upstream_id=request_id)


class ProviderPool:
    def __init__(self, settings):
        self.clients = {}
        for name, key, url in (
            ("deepseek", settings.deepseek_api_key, "https://api.deepseek.com"),
            ("kimi", settings.moonshot_api_key, "https://api.moonshot.cn/v1"),
        ):
            if key:
                self.clients[name] = AsyncOpenAI(api_key=key, base_url=url, max_retries=0)

    def configured(self, provider):
        return provider in self.clients

    async def complete(self, model, payload: dict, timeout: float) -> Result:
        client = self.clients[model.provider]
        params = dict(payload)
        extra = {}
        for key in ("thinking", "user_id"):
            if key in params:
                extra[key] = params.pop(key)
        try:
            raw = await client.chat.completions.with_raw_response.create(
                model=model.id,
                **params,
                extra_body=extra or None,
                timeout=timeout,
            )
            completion = raw.parse()
            return Result(
                completion.model_dump(mode="json", exclude_none=True),
                raw.headers.get("x-request-id"),
            )
        except openai.APIError as exc:
            raise convert_error(exc) from None

    async def stream(self, model, payload: dict, timeout: float) -> Stream:
        client = self.clients[model.provider]
        params = dict(payload)
        extra = {}
        for key in ("thinking", "user_id"):
            if key in params:
                extra[key] = params.pop(key)
        try:
            stream = await client.chat.completions.create(
                model=model.id,
                **params,
                extra_body=extra or None,
                stream=True,
                stream_options={"include_usage": True},
                timeout=timeout,
            )
            return Stream(stream, stream.response.headers.get("x-request-id"))
        except openai.APIError as exc:
            raise convert_error(exc) from None

    async def close(self):
        for client in self.clients.values():
            await client.close()


def mode_for(model, req: ChatRequest, binding_mode=None) -> dict:
    effort = req.reasoning_effort
    aliases = {"minimal": "low", "medium": "high", "xhigh": "high"}
    effort = aliases.get(effort, effort)
    forced = req.tool_choice == "required" or isinstance(req.tool_choice, NamedChoice)
    if model.provider == "kimi":
        if req.thinking is not None or effort == "none":
            raise GatewayError(400, "unsupported_mode", "This Kimi model always uses reasoning.")
        # Kimi supports required, but named functions conflict with always-on thinking.
        if isinstance(req.tool_choice, NamedChoice):
            raise GatewayError(
                400, "unsupported_tool_choice", "Forced tools require a compatible mode."
            )
        mode = {"reasoning_effort": effort or "low"}
    else:
        thinking = req.thinking.type if req.thinking else None
        if thinking == "disabled" and effort not in (None, "none"):
            raise GatewayError(400, "conflicting_mode", "Thinking and reasoning_effort conflict.")
        if thinking == "enabled" and effort == "none":
            raise GatewayError(400, "conflicting_mode", "Thinking and reasoning_effort conflict.")
        enabled = thinking == "enabled" or (effort is not None and effort != "none")
        if forced and enabled:
            raise GatewayError(
                400, "unsupported_tool_choice", "Forced tools require non-thinking mode."
            )
        if thinking is None and effort is None:
            enabled = model.id == "deepseek-v4-pro" and not forced
        mode = {"thinking": {"type": "enabled" if enabled else "disabled"}}
        if enabled:
            mode["reasoning_effort"] = effort or "high"
    if binding_mode is not None:
        if (
            model.provider == "deepseek"
            and forced
            and binding_mode.get("thinking", {}).get("type") == "enabled"
        ):
            raise GatewayError(
                400, "unsupported_tool_choice", "Bound thinking mode cannot force tools."
            )
        if (req.thinking is not None or req.reasoning_effort is not None) and mode != binding_mode:
            raise GatewayError(
                400, "tool_mode_mismatch", "Continue tools with the original reasoning mode."
            )
        return dict(binding_mode)
    return mode


def compatible(model, req, grant) -> bool:
    if req.has_images and not model.vision:
        return False
    if req.tools and not model.tools:
        return False
    if req.response_format and req.response_format.type not in model.formats:
        return False
    # DeepSeek strict tool schemas require a separate beta endpoint, outside this MVP.
    if model.provider == "deepseek" and any(t.function.strict for t in req.tools or []):
        return False
    output = req.max_tokens or req.max_completion_tokens or grant.max_output_tokens
    if output > min(grant.max_output_tokens, model.max_output_tokens):
        return False
    if req.text_bound() + output > model.context_tokens:
        return False
    try:
        mode_for(model, req)
    except GatewayError:
        return False
    return True


def payload_for(model, req, caller, binding_mode=None) -> tuple[dict, dict]:
    payload = req.payload()
    payload.pop("thinking", None)
    payload.pop("reasoning_effort", None)
    payload.pop("max_completion_tokens", None)
    payload["max_tokens"] = (
        req.max_tokens or req.max_completion_tokens or caller.grant.max_output_tokens
    )
    mode = mode_for(model, req, binding_mode)
    payload.update(mode)
    # Identity is server derived, including provider-side cache isolation where supported.
    if model.provider == "deepseek":
        payload["user_id"] = caller.company.id
    return payload, mode


def normalize_usage(raw) -> dict:
    result = {"usage_known": False, "raw_usage": None}
    fields = (
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "cached_tokens",
        "cache_write_tokens",
        "reasoning_tokens",
        "image_tokens",
    )
    result.update(dict.fromkeys(fields))
    if not isinstance(raw, dict):
        return result

    def number(value):
        return value if type(value) is int and 0 <= value <= 100_000_000 else None

    input_n, output_n, total = (
        number(raw.get(k)) for k in ("prompt_tokens", "completion_tokens", "total_tokens")
    )
    safe = {
        k: v
        for k, v in raw.items()
        if k
        in (
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
            "prompt_cache_hit_tokens",
            "prompt_cache_miss_tokens",
        )
        and number(v) is not None
    }
    for key in ("prompt_tokens_details", "completion_tokens_details"):
        detail = raw.get(key)
        if isinstance(detail, dict):
            safe[key] = {
                k: v
                for k, v in detail.items()
                if k
                in (
                    "cached_tokens",
                    "cache_write_tokens",
                    "reasoning_tokens",
                    "image_tokens",
                    "text_tokens",
                )
                and number(v) is not None
            }
    result["raw_usage"] = safe
    if input_n is None or output_n is None or total is None or input_n + output_n != total:
        return result
    prompt = safe.get("prompt_tokens_details", {})
    completion = safe.get("completion_tokens_details", {})
    details = {
        "cached_tokens": prompt.get("cached_tokens", safe.get("prompt_cache_hit_tokens")),
        "cache_write_tokens": prompt.get("cache_write_tokens"),
        "image_tokens": prompt.get("image_tokens"),
        "reasoning_tokens": completion.get("reasoning_tokens"),
    }
    for key, value in details.items():
        limit = output_n if key == "reasoning_tokens" else input_n
        if value is not None and value <= limit:
            result[key] = value
    result.update(
        usage_known=True, input_tokens=input_n, output_tokens=output_n, total_tokens=total
    )
    return result

"""Run one explicitly selected pp-router example; real endpoints incur token usage."""

import argparse
import asyncio
import base64
import json
import os
from pathlib import Path
from uuid import uuid4

from openai import AsyncOpenAI


def trace_headers():
    return {"X-Trace-ID": "suite-example-" + uuid4().hex}


def show(raw):
    result = raw.parse()
    print("request_id:", raw.headers.get("x-request-id"))
    print("model:", result.model)
    print("usage:", result.usage.model_dump() if result.usage else "unknown")
    print("finish_reason:", result.choices[0].finish_reason)
    return result


async def text_example(client):
    raw = await client.chat.completions.with_raw_response.create(
        model="deepseek-flash",
        messages=[{"role": "user", "content": "只回复 OK。"}],
        max_tokens=32,
        extra_headers=trace_headers(),
    )
    result = show(raw)
    print(result.choices[0].message.content)
    return result


async def stream_example(client):
    raw = await client.chat.completions.with_raw_response.create(
        model="deepseek-flash",
        messages=[{"role": "user", "content": "用一句话解释 token。"}],
        max_tokens=128,
        stream=True,
        stream_options={"include_usage": True},
        extra_headers=trace_headers(),
    )
    print("request_id:", raw.headers.get("x-request-id"))
    stream = raw.parse()
    usage = None
    text = []
    finish_reason = None
    async with stream:
        async for chunk in stream:
            if chunk.usage is not None:
                usage = chunk.usage
            # The usage chunk can have choices=[]; do not index choices[0] blindly.
            for choice in chunk.choices:
                if choice.finish_reason is not None:
                    finish_reason = choice.finish_reason
                content = choice.delta.content or ""
                text.append(content)
                print(content, end="", flush=True)
    if finish_reason is None:
        raise RuntimeError("Stream ended without a finish reason; check request details")
    print("\nfinish_reason:", finish_reason)
    print("usage:", usage.model_dump() if usage else "unknown; check request details")
    return "".join(text), usage


async def image_example(client, path):
    mime = {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".webp": "image/webp", ".gif": "image/gif",
    }.get(path.suffix.lower())
    if mime is None:
        raise ValueError("Use PNG, JPEG, WebP or GIF")
    data = path.read_bytes()
    if not 0 < len(data) <= 5 * 1024 * 1024:
        raise ValueError("Image must be between 1 byte and 5 MiB")
    url = f"data:{mime};base64," + base64.b64encode(data).decode()
    raw = await client.chat.completions.with_raw_response.create(
        model="deepseek-flash",
        messages=[{"role": "user", "content": [
            {"type": "text", "text": "用一句话描述这张图片。"},
            {"type": "image_url", "image_url": {"url": url}},
        ]}],
        max_tokens=256,
        extra_headers=trace_headers(),
    )
    result = show(raw)
    print(result.choices[0].message.content)
    return result


async def json_example(client):
    raw = await client.chat.completions.with_raw_response.create(
        model="auto",
        messages=[{"role": "user", "content": "返回 JSON：ok 为 true。"}],
        max_tokens=256,
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "result", "strict": True,
                "schema": {
                    "type": "object", "properties": {"ok": {"type": "boolean"}},
                    "required": ["ok"], "additionalProperties": False,
                },
            },
        },
        extra_headers=trace_headers(),
    )
    result = show(raw)
    if result.choices[0].finish_reason != "stop":
        raise RuntimeError("JSON output did not finish normally; do not treat it as complete")
    value = json.loads(result.choices[0].message.content)
    if set(value) != {"ok"} or type(value["ok"]) is not bool:
        raise ValueError("Response did not satisfy the application schema")
    print(value)
    return value


def lookup_demo_order(arguments):
    # Real applications must also enforce the authenticated user's business permissions.
    if arguments != {"order_id": "demo-001"}:
        raise ValueError("This example only allows the fixed demo order")
    return {"order_id": "demo-001", "status": "shipped"}


async def tools_example(client):
    tools = [{"type": "function", "function": {
        "name": "lookup_order", "description": "查询演示订单的状态",
        "parameters": {
            "type": "object", "properties": {"order_id": {"type": "string"}},
            "required": ["order_id"], "additionalProperties": False,
        },
    }}]
    messages = [{"role": "user", "content": "请查询订单 demo-001 的状态。"}]
    raw = await client.chat.completions.with_raw_response.create(
        model="deepseek-flash", messages=messages, tools=tools,
        tool_choice={"type": "function", "function": {"name": "lookup_order"}},
        reasoning_effort="none", max_tokens=256, extra_headers=trace_headers(),
    )
    first = show(raw)
    assistant = first.choices[0].message
    if not assistant.tool_calls:
        raise RuntimeError("Expected a tool call; no automatic retry is performed")
    # Preserve reasoning_content and tool IDs when returning the assistant message.
    messages.append(assistant.model_dump(exclude_none=True))
    for call in assistant.tool_calls:
        if call.function.name != "lookup_order":
            raise ValueError("Unknown tool name")
        value = lookup_demo_order(json.loads(call.function.arguments))
        messages.append({
            "role": "tool", "tool_call_id": call.id,
            "content": json.dumps(value, ensure_ascii=False),
        })
    raw = await client.chat.completions.with_raw_response.create(
        model="auto", messages=messages, tools=tools, tool_choice="none",
        max_tokens=256, extra_headers=trace_headers(),
    )
    second = show(raw)
    print(second.choices[0].message.content)
    return first, second


async def run(args):
    base_url = os.environ["PP_ROUTER_BASE_URL"].rstrip("/")
    if not base_url.endswith("/v1"):
        raise ValueError("PP_ROUTER_BASE_URL must end with /v1")
    async with AsyncOpenAI(
        api_key=os.environ["PP_ROUTER_API_KEY"],
        base_url=base_url, max_retries=0, timeout=210.0,
    ) as client:
        if args.case == "image":
            await image_example(client, args.image)
        else:
            await {
                "text": text_example, "stream": stream_example,
                "json": json_example, "tools": tools_example,
            }[args.case](client)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", choices=["text", "stream", "image", "json", "tools"])
    parser.add_argument("--image", type=Path)
    args = parser.parse_args()
    if args.case == "image" and args.image is None:
        parser.error("image requires --image PATH")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()

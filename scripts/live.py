"""Explicit real-provider checks. Every model call goes through the running gateway."""

import argparse
import asyncio
import base64
import json
from pathlib import Path
import sys
import time

import httpx
from openai import AsyncOpenAI

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pprouter.config import Settings  # noqa: E402


def image_message(text):
    image = base64.b64encode((ROOT / "tests/fixtures/red-square.png").read_bytes()).decode()
    return {
        "role": "user",
        "content": [
            {"type": "text", "text": text},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + image}},
        ],
    }


def text_message(text):
    return {"role": "user", "content": text}


async def run(args):
    settings = Settings.from_env()
    if not settings.deepseek_api_key or not settings.moonshot_api_key:
        raise SystemExit(
            "Configure DEEPSEEK_API_KEY and MOONSHOT_API_KEY in .env, restart make dev, then retry. No mock fallback is used."
        )
    credentials = json.loads(Path(args.credentials).read_text())
    async with httpx.AsyncClient(base_url=args.base, timeout=240) as admin:
        response = await admin.post("/admin/v1/auth/login", json=credentials["admin"])
        response.raise_for_status()
        admin.headers["x-csrf-token"] = response.json()["csrf_token"]
        models = (await admin.get("/admin/v1/models")).json()
        if not all(m["configured"] and m["enabled"] for m in models):
            raise SystemExit(
                "All three initial models must be enabled with both providers configured."
            )
        before = (await admin.get("/admin/v1/reports/monthly")).json()["summary"]
        clients = {
            name: AsyncOpenAI(
                api_key=v["api_key"], base_url=args.base + "/v1", max_retries=0, timeout=240
            )
            for name, v in credentials["applications"].items()
        }
        outcomes, request_ids = [], []
        previous_tokens = 0
        if args.command == "smoke" and getattr(args, "resume", False):
            progress = json.loads((ROOT / ".local/live-progress.json").read_text())
            if progress["command"] != "smoke":
                raise SystemExit("Resume requires a smoke progress file.")
            outcomes, request_ids = progress["cases"], progress["request_ids"]
            for request_id in request_ids:
                record = (await admin.get("/admin/v1/requests/" + request_id)).json()
                previous_tokens += sum(a["total_tokens"] or 0 for a in record["attempts"])
        completed_labels = {row["case"] for row in outcomes}
        try:

            async def completion(app, label, **payload):
                if label in completed_labels and "/tool-" not in label:
                    return None
                raw = await clients[app].chat.completions.with_raw_response.create(**payload)
                # SDK's legacy raw response parser is synchronous.
                result = raw.parse()
                request_id = raw.headers["x-request-id"]
                request_ids.append(request_id)
                assert result.usage is not None, f"{label}: missing usage"
                outcomes.append(
                    {
                        "case": label,
                        "model": result.model,
                        "request_id": request_id,
                        "tokens": result.usage.total_tokens,
                    }
                )
                print(
                    label
                    + ": "
                    + result.model
                    + " / "
                    + str(result.usage.total_tokens)
                    + " tokens",
                    flush=True,
                )
                return result

            if args.command == "evaluate":
                fixtures = json.loads((ROOT / "tests/fixtures/routing_cases.json").read_text())
                all_keys = (await admin.get("/admin/v1/keys")).json()
                key_ids = {
                    name: next(
                        k["id"]
                        for k in all_keys
                        if k["grant_id"] == item["grant_id"]
                        and k["enabled"]
                        and k["environment"] == "local"
                    )
                    for name, item in credentials["applications"].items()
                }
                hits, constraint_hits, confirmed_tokens = 0, 0, 0
                for case in fixtures:
                    message = (
                        image_message(case["query"])
                        if case["image"]
                        else text_message(case["query"])
                    )
                    response = await admin.post(
                        "/admin/v1/routing/preview",
                        json={
                            "key_id": key_ids["vision" if case["image"] else "chat"],
                            "request": {"model": "auto", "messages": [message], "max_tokens": 256},
                        },
                    )
                    response.raise_for_status()
                    preview = response.json()
                    request_id = preview["request_id"]
                    request_ids.append(request_id)
                    record = (await admin.get("/admin/v1/requests/" + request_id)).json()
                    route = record["routing"]
                    hit = (
                        route["selected_model"] in case["acceptable_models"]
                        and not route["degraded"]
                    )
                    constraint = route["selected_model"] in route["candidates"]
                    assert record["actual_model"] is None
                    assert all(a["phase"] == "routing" for a in record["attempts"])
                    tokens = sum(a["total_tokens"] or 0 for a in record["attempts"])
                    confirmed_tokens += tokens
                    hits += hit
                    constraint_hits += constraint
                    outcomes.append(
                        {
                            "case": case["id"],
                            "request_id": request_id,
                            "acceptable": hit,
                            "constraint_passed": constraint,
                            "route": route,
                            "tokens": tokens,
                            "usage_unknown": sum(not a["usage_known"] for a in record["attempts"]),
                        }
                    )
                    print(
                        f"{case['id']}: {route['selected_model']} / acceptable={hit} / {tokens} tokens",
                        flush=True,
                    )
                    # Stop if usage is unknown or unexpectedly large; avoid blind repeated spending.
                    if outcomes[-1]["usage_unknown"] or confirmed_tokens > 30000:
                        break
                score = hits / len(fixtures)
                result = {
                    "mode": "live",
                    "cases": outcomes,
                    "accuracy": score,
                    "completed_cases": len(outcomes),
                    "execution_skipped": True,
                    "confirmed_tokens": confirmed_tokens,
                    "constraint_rate": constraint_hits / len(fixtures),
                    "timestamp": time.time(),
                }
                path = ROOT / ".local/routing-evaluation.json"
                path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
                print(
                    f"Routing accuracy: {score:.1%}; constraints: {constraint_hits}/{len(fixtures)}"
                )
                assert score >= 0.9 and constraint_hits == len(fixtures), (
                    f"Routing acceptance failed; see {path}"
                )
            else:
                for model in ("deepseek-flash", "deepseek-v4-pro", "kimi-k3.1-pro"):
                    await completion(
                        "chat",
                        model + "/text",
                        model=model,
                        messages=[text_message("请只回复 OK。")],
                        reasoning_effort="low" if model != "deepseek-flash" else "none",
                        max_tokens=256,
                    )
                await completion(
                    "chat",
                    "auto",
                    model="auto",
                    messages=[text_message("请翻译为英文：你好，世界。")],
                    max_tokens=256,
                )
                for model in ("deepseek-flash", "kimi-k3.1-pro"):
                    await completion(
                        "vision",
                        model + "/image",
                        model=model,
                        messages=[image_message("图中主要是什么颜色？")],
                        max_tokens=256,
                    )
                    if model + "/stream" in completed_labels:
                        continue
                    stream = await clients["chat"].chat.completions.create(
                        model=model,
                        messages=[text_message("请回复一声你好。")],
                        max_tokens=256,
                        stream=True,
                        stream_options={"include_usage": True},
                    )
                    usage = None
                    async with stream:
                        async for part in stream:
                            if part.id.startswith("chatcmpl-") and part.id[9:] not in request_ids:
                                request_ids.append(part.id[9:])
                            if part.usage:
                                usage = part.usage
                    assert usage is not None, model + ": stream usage missing"
                    outcomes.append({"case": model + "/stream", "tokens": usage.total_tokens})
                result = await completion(
                    "chat",
                    "json-object",
                    model="deepseek-flash",
                    messages=[text_message("仅返回 JSON 对象，字段 ok 的值为 true。")],
                    max_tokens=256,
                    response_format={"type": "json_object"},
                )
                if result is not None:
                    assert json.loads(result.choices[0].message.content)["ok"] is True
                result = await completion(
                    "chat",
                    "json-schema",
                    model="auto",
                    messages=[text_message("请返回 ok 为 true 的 JSON。")],
                    max_tokens=256,
                    response_format={
                        "type": "json_schema",
                        "json_schema": {
                            "name": "check",
                            "strict": True,
                            "schema": {
                                "type": "object",
                                "properties": {"ok": {"type": "boolean"}},
                                "required": ["ok"],
                                "additionalProperties": False,
                            },
                        },
                    },
                )
                if result is not None:
                    assert json.loads(result.choices[0].message.content) == {"ok": True}
                for model in ("deepseek-flash", "kimi-k3.1-pro"):
                    if model + "/tool-resume" in completed_labels:
                        continue
                    tools = [
                        {
                            "type": "function",
                            "function": {
                                "name": "get_weather",
                                "description": "Return local demo weather for a city.",
                                "parameters": {
                                    "type": "object",
                                    "properties": {"city": {"type": "string"}},
                                    "required": ["city"],
                                },
                            },
                        }
                    ]
                    messages = [text_message("请通过 get_weather 工具查询上海天气，然后简短转述。")]
                    first = await completion(
                        "agent",
                        model + "/tool-start",
                        model=model,
                        messages=messages,
                        tools=tools,
                        tool_choice="required",
                        max_tokens=512,
                    )
                    assistant = first.choices[0].message
                    assert assistant.tool_calls, "Expected tool call"
                    messages.append(
                        assistant.model_dump(
                            exclude={"refusal", "annotations", "audio"}, exclude_none=True
                        )
                    )
                    for tool in assistant.tool_calls:
                        assert tool.function.name == "get_weather"
                        json.loads(tool.function.arguments)
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tool.id,
                                "content": json.dumps(
                                    {
                                        "city": "上海",
                                        "condition": "晴",
                                        "celsius": 22,
                                        "source": "local_demo",
                                    }
                                ),
                            }
                        )
                    final = await completion(
                        "agent",
                        model + "/tool-resume",
                        model="auto",
                        messages=messages,
                        tools=tools,
                        max_tokens=512,
                    )
                    assert final.model == model and final.choices[0].message.content
                records = [
                    (await admin.get("/admin/v1/requests/" + id)).json() for id in request_ids
                ]
                attempts = [a for r in records for a in r["attempts"]]
                after = (await admin.get("/admin/v1/reports/monthly")).json()["summary"]
                confirmed = sum(a["total_tokens"] or 0 for a in attempts)
                assert (
                    after["total_tokens"] - (before["total_tokens"] or 0)
                    == confirmed - previous_tokens
                )
                assert all(a["usage_known"] for a in attempts), (
                    "Some upstream usage remains unknown"
                )
                csv = await admin.get("/admin/v1/reports/monthly.csv")
                assert csv.status_code == 200 and "pp_admin" in csv.text
                path = ROOT / ".local/live-smoke.json"
                path.write_text(
                    json.dumps(
                        {
                            "mode": "live",
                            "cases": outcomes,
                            "request_ids": request_ids,
                            "confirmed_tokens": confirmed,
                            "timestamp": time.time(),
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                print("Live smoke and usage reconciliation passed: " + str(path))
        finally:
            (ROOT / ".local/live-progress.json").write_text(
                json.dumps(
                    {
                        "command": args.command,
                        "cases": outcomes,
                        "request_ids": request_ids,
                        "timestamp": time.time(),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            for client in clients.values():
                await client.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["smoke", "evaluate"])
    parser.add_argument(
        "--resume", action="store_true", help="Skip completed smoke cases after a failed run."
    )
    parser.add_argument("--base", default="http://127.0.0.1:4000")
    parser.add_argument("--credentials", default=str(ROOT / ".local/credentials.json"))
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()

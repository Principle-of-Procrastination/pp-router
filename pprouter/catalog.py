MODELS = [
    dict(id="deepseek-flash", provider="deepseek", vision=True, formats=["text", "json_object"]),
    dict(id="deepseek-v4-pro", provider="deepseek", vision=False, formats=["text", "json_object"]),
    dict(
        id="kimi-k3.1-pro",
        provider="kimi",
        vision=True,
        formats=["text", "json_object", "json_schema"],
    ),
]
MODEL_IDS = [m["id"] for m in MODELS]
DEFAULT_POLICY = {
    "classifier_model": "deepseek-flash",
    "default_model": "deepseek-flash",
    "fallback_order": ["deepseek-flash", "kimi-k3.1-pro", "deepseek-v4-pro"],
    "task_routes": {
        "general": "deepseek-flash",
        "reasoning": "deepseek-v4-pro",
        "coding": "kimi-k3.1-pro",
        "agent": "kimi-k3.1-pro",
        "vision": "kimi-k3.1-pro",
        "structured": "kimi-k3.1-pro",
    },
}

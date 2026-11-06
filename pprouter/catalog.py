APPLICATIONS = [
    dict(
        code="pp_code",
        name="PP Code",
        description="编程、代码审查、工程理解及通过工具完成开发任务",
    ),
    dict(code="pp_chat", name="PP Chat", description="对话、问答、写作、摘要及通用 AI 助手"),
    dict(code="pp_cad", name="PP CAD", description="CAD 绘图、图纸理解、设计辅助及相关业务任务"),
]

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

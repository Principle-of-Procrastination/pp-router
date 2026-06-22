import os
from dataclasses import dataclass
from enum import Enum


class Tier(str, Enum):
    SIMPLE = "SIMPLE"
    MEDIUM = "MEDIUM"
    COMPLEX = "COMPLEX"
    REASONING = "REASONING"


@dataclass(frozen=True, slots=True)
class BuiltinModel:
    id: str
    litellm_model: str
    tiers: tuple[Tier, ...]
    api_base: str
    api_key_env: str


# OpenAI-compatible endpoints. litellm has no native provider for either vendor,
# so every model is called via the `openai/` prefix + its own api_base/api_key.
BIGMODEL_API_BASE = "https://open.bigmodel.cn/api/paas/v4"
DASHSCOPE_API_BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"

BUILTIN_MODELS: tuple[BuiltinModel, ...] = (
    BuiltinModel(
        "glm-4.7-flash", "openai/glm-4.7-flash",
        (Tier.SIMPLE,), BIGMODEL_API_BASE, "BIGMODEL_API_KEY",
    ),
    BuiltinModel(
        "glm-4.7", "openai/glm-4.7",
        (Tier.MEDIUM,), BIGMODEL_API_BASE, "BIGMODEL_API_KEY",
    ),
    BuiltinModel(
        "glm-5.1", "openai/glm-5.1",
        (Tier.COMPLEX,), BIGMODEL_API_BASE, "BIGMODEL_API_KEY",
    ),
    BuiltinModel(
        "qwen3.7-max", "openai/qwen3.7-max",
        (Tier.REASONING,), DASHSCOPE_API_BASE, "QWEN_API_KEY",
    ),
)

TIER_MAP: dict[Tier, str] = {
    Tier.SIMPLE: "glm-4.7-flash",
    Tier.MEDIUM: "glm-4.7",
    Tier.COMPLEX: "glm-5.1",
    Tier.REASONING: "qwen3.7-max",
}

DEFAULT_GROUP = "glm-4.7-flash"

HISTORY_PATH = "history.jsonl"


def get_api_key(env_name: str) -> str:
    key = os.environ.get(env_name, "").strip()
    if not key:
        raise RuntimeError(f"environment variable {env_name} is not set")
    return key

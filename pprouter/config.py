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


API_BASE = "https://open.bigmodel.cn/api/paas/v4"
API_KEY_ENV = "BIGMODEL_API_KEY"

BUILTIN_MODELS: tuple[BuiltinModel, ...] = (
    BuiltinModel("glm-4.7-flash", "openai/glm-4.7-flash", (Tier.SIMPLE, Tier.MEDIUM)),
    BuiltinModel("glm-5.1", "openai/glm-5.1", (Tier.COMPLEX, Tier.REASONING)),
)

TIER_MAP: dict[Tier, str] = {
    Tier.SIMPLE: "glm-4.7-flash",
    Tier.MEDIUM: "glm-4.7-flash",
    Tier.COMPLEX: "glm-5.1",
    Tier.REASONING: "glm-5.1",
}

DEFAULT_GROUP = "glm-4.7-flash"


def get_api_key() -> str:
    key = os.environ.get(API_KEY_ENV, "").strip()
    if not key:
        raise RuntimeError(f"environment variable {API_KEY_ENV} is not set")
    return key

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


# OpenAI-compatible endpoints. litellm has no native provider for these vendors,
# so every model is called via the `openai/` prefix + its own api_base/api_key.
STEPFUN_API_BASE = "https://api.stepfun.com/v1"
BIGMODEL_API_BASE = "https://open.bigmodel.cn/api/paas/v4"
BUILTIN_MODELS: tuple[BuiltinModel, ...] = (
    BuiltinModel(
        "step-3.7-flash", "openai/step-3.7-flash",
        (Tier.SIMPLE,), STEPFUN_API_BASE, "STEP_API_KEY",
    ),
    BuiltinModel(
        "glm-4.7", "openai/glm-4.7",
        (Tier.MEDIUM,), BIGMODEL_API_BASE, "BIGMODEL_API_KEY",
    ),
    BuiltinModel(
        "glm-5.1", "openai/glm-5.1",
        (Tier.COMPLEX, Tier.REASONING), BIGMODEL_API_BASE, "BIGMODEL_API_KEY",
    ),
)

TIER_MAP: dict[Tier, str] = {
    Tier.SIMPLE: "step-3.7-flash",
    Tier.MEDIUM: "glm-4.7",
    Tier.COMPLEX: "glm-5.1",
    Tier.REASONING: "glm-5.1",
}

DEFAULT_GROUP = "step-3.7-flash"

# Keep non-reasoning tiers responsive. GLM supports disabling thinking; StepFun
# 3.7 Flash only supports lowering reasoning effort, not a true off switch.
MODEL_COMPLETION_KWARGS = {
    "step-3.7-flash": {"extra_body": {"reasoning_effort": "low"}},
    "glm-4.7": {"extra_body": {"thinking": {"type": "disabled"}}},
    "glm-5.1": {"extra_body": {"thinking": {"type": "disabled"}}},
}

DEFAULT_CORS_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "https://pprouter-web-principleprocrastination-d6cb34f.webapps.tcloudbase.com",
)


@dataclass(frozen=True, slots=True)
class Settings:
    access_key: str
    session_secret: str
    cors_origins: tuple[str, ...]
    session_ttl_seconds: int
    login_attempts_per_minute: int
    chat_requests_per_minute: int
    max_concurrent_requests: int
    upstream_timeout_seconds: float
    stream_heartbeat_seconds: float
    max_output_tokens: int
    history_path: str
    cloudbase_env_id: str | None
    cloudbase_api_key: str | None
    cloudbase_history_collection: str

    @classmethod
    def from_env(cls) -> "Settings":
        access_key = _required_secret("PPROUTER_ACCESS_KEY", min_length=24)
        session_secret = _required_secret("PPROUTER_SESSION_SECRET", min_length=32)
        cloudbase_env_id = _optional_env("CLOUDBASE_ENV_ID")
        cloudbase_api_key = _optional_env("CLOUDBASE_API_KEY")
        if bool(cloudbase_env_id) != bool(cloudbase_api_key):
            raise RuntimeError(
                "CLOUDBASE_ENV_ID and CLOUDBASE_API_KEY must be configured together"
            )

        return cls(
            access_key=access_key,
            session_secret=session_secret,
            cors_origins=get_cors_origins(),
            session_ttl_seconds=_int_env("SESSION_TTL_SECONDS", 43_200, 300, 604_800),
            login_attempts_per_minute=_int_env(
                "LOGIN_ATTEMPTS_PER_MINUTE", 5, 1, 60
            ),
            chat_requests_per_minute=_int_env(
                "CHAT_REQUESTS_PER_MINUTE", 30, 1, 600
            ),
            max_concurrent_requests=_int_env("MAX_CONCURRENT_REQUESTS", 4, 1, 64),
            upstream_timeout_seconds=_float_env(
                "UPSTREAM_TIMEOUT_SECONDS", 180.0, 10.0, 900.0
            ),
            stream_heartbeat_seconds=_float_env(
                "STREAM_HEARTBEAT_SECONDS", 15.0, 1.0, 60.0
            ),
            max_output_tokens=_int_env("MAX_OUTPUT_TOKENS", 4096, 128, 32_768),
            history_path=os.environ.get("HISTORY_PATH", "history.db").strip()
            or "history.db",
            cloudbase_env_id=cloudbase_env_id,
            cloudbase_api_key=cloudbase_api_key,
            cloudbase_history_collection=os.environ.get(
                "CLOUDBASE_HISTORY_COLLECTION", "pprouter_history"
            ).strip()
            or "pprouter_history",
        )


def get_api_key(env_name: str) -> str:
    key = os.environ.get(env_name, "").strip()
    if not key:
        raise RuntimeError(f"environment variable {env_name} is not set")
    return key


def get_cors_origins() -> tuple[str, ...]:
    raw = os.environ.get("CORS_ORIGINS", "")
    if not raw.strip():
        return DEFAULT_CORS_ORIGINS
    origins = tuple(dict.fromkeys(part.strip().rstrip("/") for part in raw.split(",") if part.strip()))
    if not origins or "*" in origins:
        raise RuntimeError("CORS_ORIGINS must contain explicit origins, not '*'")
    return origins


def docs_enabled() -> bool:
    return os.environ.get("PPROUTER_DOCS_ENABLED", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def _required_secret(name: str, *, min_length: int) -> str:
    value = os.environ.get(name, "").strip()
    if len(value) < min_length:
        raise RuntimeError(f"environment variable {name} must be at least {min_length} characters")
    return value


def _optional_env(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None


def _int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.environ.get(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"environment variable {name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise RuntimeError(f"environment variable {name} must be between {minimum} and {maximum}")
    return value


def _float_env(name: str, default: float, minimum: float, maximum: float) -> float:
    raw = os.environ.get(name, str(default)).strip()
    try:
        value = float(raw)
    except ValueError as exc:
        raise RuntimeError(f"environment variable {name} must be a number") from exc
    if not minimum <= value <= maximum:
        raise RuntimeError(f"environment variable {name} must be between {minimum} and {maximum}")
    return value

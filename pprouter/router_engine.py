from typing import Any

from litellm import Router

from pprouter.config import BUILTIN_MODELS, get_api_key


def build_model_list() -> list[dict[str, Any]]:
    return [
        {
            "model_name": m.id,
            "litellm_params": {
                "model": m.litellm_model,
                "api_base": m.api_base,
                "api_key": get_api_key(m.api_key_env),
            },
            "model_info": {
                "id": m.id,
                "cache_creation_input_token_cost": 0.0,
                "cache_read_input_token_cost": 0.0,
            },
        }
        for m in BUILTIN_MODELS
    ]


def build_router() -> Router:
    return Router(
        model_list=build_model_list(),
        num_retries=1,
        max_fallbacks=1,
        fallbacks=[
            {"step-3.7-flash": ["glm-4.7"]},
            {"glm-4.7": ["glm-5.1"]},
        ],
        allowed_fails=2,
        cooldown_time=30,
        enable_pre_call_checks=True,
    )

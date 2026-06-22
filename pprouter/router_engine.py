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
            "model_info": {"id": m.id},
        }
        for m in BUILTIN_MODELS
    ]


def build_router() -> Router:
    return Router(model_list=build_model_list())

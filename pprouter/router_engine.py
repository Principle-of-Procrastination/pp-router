from typing import Any

from litellm import Router

from pprouter.config import API_BASE, BUILTIN_MODELS, get_api_key


def build_model_list() -> list[dict[str, Any]]:
    api_key = get_api_key()
    return [
        {
            "model_name": m.id,
            "litellm_params": {
                "model": m.litellm_model,
                "api_base": API_BASE,
                "api_key": api_key,
            },
            "model_info": {"id": m.id},
        }
        for m in BUILTIN_MODELS
    ]


def build_router() -> Router:
    return Router(model_list=build_model_list())

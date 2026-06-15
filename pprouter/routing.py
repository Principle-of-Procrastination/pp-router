from litellm import Router
from litellm.router_strategy.complexity_router import ComplexityRouter

from pprouter.config import DEFAULT_GROUP, TIER_MAP, Tier
from pprouter.schemas import RoutingInfo


class DifficultyRouter:
    def __init__(self, router: Router) -> None:
        self._classifier = ComplexityRouter(
            model_name="pp-difficulty-classifier",
            litellm_router_instance=router,
        )

    def route(self, messages: list[dict[str, str]]) -> RoutingInfo:
        prompt = _last_user_text(messages)
        if not prompt.strip():
            return RoutingInfo(target_group=DEFAULT_GROUP)

        tier_value, score, _signals = self._classifier.classify(
            prompt, _system_text(messages)
        )
        tier = Tier(tier_value.value)
        group = TIER_MAP.get(tier, DEFAULT_GROUP)
        return RoutingInfo(target_group=group, tier=tier.value, score=score)


def _last_user_text(messages: list[dict[str, str]]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            return message.get("content") or ""
    return ""


def _system_text(messages: list[dict[str, str]]) -> str:
    return " ".join(
        message.get("content") or ""
        for message in messages
        if message.get("role") == "system"
    )

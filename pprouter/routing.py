from litellm import Router
from litellm.router_strategy.complexity_router import ComplexityRouter

from pprouter.config import DEFAULT_GROUP, TIER_MAP, Tier
from pprouter.schemas import RoutingInfo
from pprouter.zh_complexity import ChineseComplexityResult, classify_chinese


TIER_RANK: dict[Tier, int] = {
    Tier.SIMPLE: 0,
    Tier.MEDIUM: 1,
    Tier.COMPLEX: 2,
    Tier.REASONING: 3,
}


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

        system_prompt = _system_text(messages)
        tier_value, score, _signals = self._classifier.classify(prompt, system_prompt)
        tier = Tier(tier_value.value)
        zh_result = classify_chinese(prompt, system_prompt)
        tier, score = _merge_classification(tier, score, zh_result)

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


def _merge_classification(
    base_tier: Tier,
    base_score: float,
    zh_result: ChineseComplexityResult | None,
) -> tuple[Tier, float]:
    if zh_result is None:
        return base_tier, base_score

    if TIER_RANK[zh_result.tier] >= TIER_RANK[base_tier]:
        return zh_result.tier, zh_result.score
    return base_tier, base_score

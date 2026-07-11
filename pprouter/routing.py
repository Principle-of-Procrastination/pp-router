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

FOLLOW_UP_MARKERS = (
    "继续",
    "接着",
    "展开",
    "详细说",
    "再详细",
    "详细一点",
    "具体一点",
    "然后呢",
    "下一步",
    "再说说",
    "还有呢",
    "还有吗",
    "为什么",
    "怎么做",
    "这个方案",
    "上述方案",
    "基于这个",
    "按这个",
    "go on",
    "continue",
    "more detail",
    "what next",
)


class DifficultyRouter:
    def __init__(self, router: Router) -> None:
        self._classifier = ComplexityRouter(
            model_name="pp-difficulty-classifier",
            litellm_router_instance=router,
        )

    def route(self, messages: list[dict[str, str]]) -> RoutingInfo:
        prompt = _routing_text(messages)
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


def _routing_text(messages: list[dict[str, str]]) -> str:
    user_texts = [
        (message.get("content") or "").strip()
        for message in messages
        if message.get("role") == "user" and (message.get("content") or "").strip()
    ]
    if not user_texts:
        return ""
    current = user_texts[-1]
    if len(user_texts) < 2 or len(current) > 60:
        return current
    current_lower = current.lower()
    if any(marker in current_lower for marker in FOLLOW_UP_MARKERS):
        return f"{user_texts[-2]}\n{current}"
    return current


def _system_text(messages: list[dict[str, str]]) -> str:
    return " ".join(
        message.get("content") or "" for message in messages if message.get("role") == "system"
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

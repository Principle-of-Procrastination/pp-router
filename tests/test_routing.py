from unittest.mock import MagicMock

from pprouter.router_engine import build_router
from pprouter.routing import DifficultyRouter


def test_short_follow_up_inherits_previous_complex_task() -> None:
    router = DifficultyRouter(MagicMock())

    result = router.route(
        [
            {
                "role": "user",
                "content": "帮我设计一个高并发订单系统，包含缓存、限流和消息队列",
            },
            {"role": "assistant", "content": "先给出整体架构。"},
            {"role": "user", "content": "继续"},
        ]
    )

    assert result.tier == "COMPLEX"
    assert result.target_group == "glm-5.1"


def test_router_has_bounded_adjacent_tier_fallbacks(monkeypatch) -> None:
    monkeypatch.setenv("STEP_API_KEY", "step-key")
    monkeypatch.setenv("BIGMODEL_API_KEY", "bigmodel-key")

    router = build_router()

    assert router.num_retries == 1
    assert router.max_fallbacks == 1
    assert router.fallbacks == [
        {"step-3.7-flash": ["glm-4.7"]},
        {"glm-4.7": ["glm-5.1"]},
    ]

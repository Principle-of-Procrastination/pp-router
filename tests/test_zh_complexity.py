from pprouter.config import Tier
from pprouter.routing import _merge_classification
from pprouter.zh_complexity import ChineseComplexityResult, classify_chinese


def test_non_chinese_prompt_is_ignored() -> None:
    assert classify_chinese("Explain database indexing") is None


def test_chinese_simple_definition_stays_simple() -> None:
    result = classify_chinese("什么是分布式数据库？")

    assert result is not None
    assert result.tier is Tier.SIMPLE


def test_chinese_technical_explanation_is_medium() -> None:
    result = classify_chinese("解释一下数据库索引为什么能加速查询")

    assert result is not None
    assert result.tier is Tier.MEDIUM


def test_chinese_architecture_design_is_complex() -> None:
    result = classify_chinese("帮我设计一个高并发订单系统，包含缓存、限流、数据库分库分表")

    assert result is not None
    assert result.tier is Tier.COMPLEX


def test_chinese_reasoning_decision_is_reasoning() -> None:
    result = classify_chinese("一步步分析我们应该用 Raft 还是 Paxos，并说明取舍")

    assert result is not None
    assert result.tier is Tier.REASONING


def test_chinese_code_and_technical_without_reasoning_caps_at_complex() -> None:
    result = classify_chinese("帮我实现一个 Python 并发限流器，支持 Redis 分布式部署")

    assert result is not None
    assert result.tier is Tier.COMPLEX


def test_chinese_result_can_upgrade_base_classifier() -> None:
    merged_tier, merged_score = _merge_classification(
        Tier.SIMPLE,
        -0.1,
        ChineseComplexityResult(Tier.COMPLEX, 0.48, ("technical",)),
    )

    assert merged_tier is Tier.COMPLEX
    assert merged_score == 0.48


def test_base_classifier_wins_when_it_is_higher() -> None:
    merged_tier, merged_score = _merge_classification(
        Tier.COMPLEX,
        0.43,
        ChineseComplexityResult(Tier.MEDIUM, 0.25, ("medium",)),
    )

    assert merged_tier is Tier.COMPLEX
    assert merged_score == 0.43


def test_overlapping_reasoning_keywords_are_counted_once() -> None:
    result = classify_chinese("深入分析一下天气")

    assert result is not None
    assert result.tier is Tier.MEDIUM
    assert result.signals == ("reasoning (深入分析)",)


def test_common_word_containing_class_character_is_not_code() -> None:
    result = classify_chinese("人类为什么需要睡眠？")

    assert result is not None
    assert result.tier is Tier.SIMPLE


def test_complex_task_is_not_downgraded_by_short_output_instruction() -> None:
    result = classify_chinese("简单回答：请设计并实现一个高并发订单系统")

    assert result is not None
    assert result.tier is Tier.COMPLEX


def test_chinese_system_prompt_does_not_reclassify_english_user_text() -> None:
    assert classify_chinese("Say hello", "你是一个代码助手") is None


def test_system_prompt_does_not_inflate_simple_chinese_request() -> None:
    result = classify_chinese(
        "你好",
        "你是资深 Python 架构师，负责设计、实现、调试和优化代码",
    )

    assert result is not None
    assert result.tier is Tier.SIMPLE


def test_constraint_dense_delivery_plan_is_complex() -> None:
    result = classify_chinese(
        "帮我写一份上线方案，要求零停机、可回滚、兼容旧客户端，同时给出监控指标和验收标准。"
    )

    assert result is not None
    assert result.tier is Tier.COMPLEX
    assert any(signal.startswith("constraints") for signal in result.signals)
    assert any(signal.startswith("deliverables") for signal in result.signals)


def test_bounded_multi_variant_rewrite_is_medium() -> None:
    result = classify_chinese(
        "把这段文字改写成正式语气，同时保留原意，不超过200字，并给出三个版本。"
    )

    assert result is not None
    assert result.tier is Tier.MEDIUM


def test_scale_and_negative_constraints_are_complex() -> None:
    result = classify_chinese(
        "不要使用 Redis，也不能改数据库表结构，请给出能支撑每秒一万请求的方案。"
    )

    assert result is not None
    assert result.tier is Tier.COMPLEX
    assert "scale requirement" in result.signals


def test_multi_criteria_decision_uses_reasoning() -> None:
    result = classify_chinese(
        "比较三种实现方案，从成本、延迟、可靠性和维护复杂度评估，并给出推荐。"
    )

    assert result is not None
    assert result.tier is Tier.REASONING


def test_diagnostic_plan_uses_reasoning() -> None:
    result = classify_chinese("分析支付偶发重复扣款的可能原因，给出排查顺序、验证方法和修复方案。")

    assert result is not None
    assert result.tier is Tier.REASONING

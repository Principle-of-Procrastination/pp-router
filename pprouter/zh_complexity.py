import re
from dataclasses import dataclass

from pprouter.config import Tier


CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")

SIMPLE_KEYWORDS = (
    "你好",
    "您好",
    "谢谢",
    "再见",
    "是什么",
    "什么是",
    "谁是",
    "哪里",
    "在哪",
    "多少",
    "几点",
    "几号",
    "翻译",
    "一句话",
    "简短",
    "简单回答",
)

MEDIUM_ACTION_KEYWORDS = (
    "解释",
    "说明",
    "总结",
    "概括",
    "对比",
    "区别",
    "改写",
    "润色",
    "建议",
    "怎么做",
    "如何",
    "步骤",
)

COMPLEX_ACTION_KEYWORDS = (
    "设计",
    "实现",
    "落地",
    "重构",
    "优化",
    "排查",
    "调试",
    "修复",
    "迁移",
    "压测",
    "建模",
    "部署",
    "接入",
    "集成",
    "审计",
)

CODE_KEYWORDS = (
    "代码",
    "函数",
    "类定义",
    "面向对象",
    "class",
    "脚本",
    "python",
    "javascript",
    "typescript",
    "react",
    "vue",
    "node",
    "java",
    "golang",
    "rust",
    "sql",
    "正则",
    "算法",
    "数据结构",
    "时间复杂度",
    "空间复杂度",
    "算法复杂度",
    "单元测试",
    "sdk",
    "api",
    "接口",
    "报错",
    "异常",
    "bug",
)

TECHNICAL_KEYWORDS = (
    "数据库",
    "索引",
    "查询",
    "事务",
    "锁",
    "缓存",
    "限流",
    "队列",
    "消息队列",
    "架构",
    "系统设计",
    "分布式",
    "微服务",
    "高并发",
    "并发",
    "吞吐",
    "吞吐量",
    "延迟",
    "性能",
    "鉴权",
    "认证",
    "授权",
    "加密",
    "安全",
    "漏洞",
    "容器",
    "kubernetes",
    "docker",
    "redis",
    "postgresql",
    "mysql",
    "mongodb",
    "http",
    "websocket",
    "rpc",
    "raft",
    "paxos",
    "一致性",
    "内存",
    "cpu",
    "gpu",
    "模型",
    "llm",
    "路由",
)

REASONING_KEYWORDS = (
    "一步步",
    "逐步",
    "推理",
    "推导",
    "证明",
    "论证",
    "分析",
    "深入分析",
    "根因",
    "根因分析",
    "思考过程",
    "逻辑",
)

DECISION_KEYWORDS = (
    "利弊",
    "优缺点",
    "优劣",
    "取舍",
    "权衡",
    "评估",
    "比较",
    "选型",
    "怎么选",
    "是否应该",
    "应不应该",
    "要不要",
    "应该用",
    "trade-off",
    "pros and cons",
)

MULTI_STEP_KEYWORDS = (
    "首先",
    "其次",
    "然后",
    "最后",
    "步骤",
    "流程",
)

CONSTRAINT_KEYWORDS = (
    "要求",
    "必须",
    "需要满足",
    "不能",
    "不得",
    "不要",
    "禁止",
    "不可",
    "只允许",
    "至少",
    "最多",
    "不超过",
    "不少于",
    "以内",
    "兼容",
    "保留",
    "保持",
    "前提",
    "限制",
    "约束",
    "零停机",
    "不停机",
    "可回滚",
    "高可用",
    "低延迟",
)

DELIVERABLE_KEYWORDS = (
    "上线方案",
    "迁移方案",
    "回滚方案",
    "修复方案",
    "监控指标",
    "验收标准",
    "排查顺序",
    "验证方法",
    "接口定义",
    "数据模型",
    "架构图",
    "测试用例",
    "风险清单",
    "方案",
    "计划",
    "清单",
    "报告",
    "文档",
    "版本",
)

EVALUATION_KEYWORDS = (
    "成本",
    "延迟",
    "可靠性",
    "可用性",
    "性能",
    "安全性",
    "维护成本",
    "维护复杂度",
    "风险",
    "收益",
    "扩展性",
    "可扩展性",
    "一致性",
)

COMPOSITION_KEYWORDS = (
    "同时",
    "并且",
    "以及",
    "还要",
    "分别",
    "包含",
    "包括",
)

MULTI_STEP_PATTERNS = (
    re.compile(r"第[一二三四五六七八九十\d]+"),
    re.compile(r"[一二三四五六七八九十\d]+[、.．]\s*"),
)

SCALE_PATTERNS = (
    re.compile(r"(?:qps|tps)\s*(?:>=|>|≥)?\s*\d+", re.IGNORECASE),
    re.compile(
        r"每(?:秒|分钟|小时).{0,8}[一二三四五六七八九十百千万亿\d]+"
        r"(?:次|请求|条|笔|个)"
    ),
    re.compile(
        r"[一二三四五六七八九十百千万亿\d]+\s*"
        r"(?:并发|用户|请求|数据|记录|订单|消息)"
    ),
    re.compile(r"(?:万级|百万|千万|亿级)(?:数据|请求|用户|并发|流量|订单)"),
)


@dataclass(frozen=True, slots=True)
class ChineseComplexityResult:
    tier: Tier
    score: float
    signals: tuple[str, ...]


def classify_chinese(prompt: str, system_prompt: str = "") -> ChineseComplexityResult | None:
    user_text = prompt.strip()
    if not _has_cjk(user_text):
        return None
    lower_user = user_text.lower()

    simple = _matches(lower_user, SIMPLE_KEYWORDS)
    medium_actions = _matches(lower_user, MEDIUM_ACTION_KEYWORDS)
    complex_actions = _matches(lower_user, COMPLEX_ACTION_KEYWORDS)
    code = _matches(lower_user, CODE_KEYWORDS)
    technical = _matches(lower_user, TECHNICAL_KEYWORDS)
    reasoning = _matches(lower_user, REASONING_KEYWORDS)
    decision = _matches(lower_user, DECISION_KEYWORDS)
    multi_step = _matches(lower_user, MULTI_STEP_KEYWORDS)
    constraints = _matches(lower_user, CONSTRAINT_KEYWORDS)
    deliverables = _matches(lower_user, DELIVERABLE_KEYWORDS)
    evaluation = _matches(lower_user, EVALUATION_KEYWORDS)
    composition = _matches(lower_user, COMPOSITION_KEYWORDS)
    scale = [pattern.pattern for pattern in SCALE_PATTERNS if pattern.search(user_text)]
    multi_step.extend(
        pattern.pattern for pattern in MULTI_STEP_PATTERNS if pattern.search(user_text)
    )

    tokens = estimate_mixed_tokens(prompt)
    question_count = prompt.count("?") + prompt.count("？")
    clause_count = len(re.findall(r"[，,；;、]", user_text))

    score = 0.0
    signals: list[str] = []

    if tokens < 8 and not (medium_actions or complex_actions or code or technical or reasoning):
        score -= 0.10
        signals.append(f"short ({tokens} tokens)")
    elif tokens > 600:
        score += 0.14
        signals.append(f"long ({tokens} tokens)")
    elif tokens > 250:
        score += 0.08
        signals.append(f"long ({tokens} tokens)")

    if simple and not (complex_actions or code):
        score -= 0.12
        signals.append(_signal("simple", simple))
    if medium_actions:
        score += 0.15
        signals.append(_signal("medium", medium_actions))
    if complex_actions:
        score += 0.22 if len(complex_actions) >= 2 else 0.16
        signals.append(_signal("complex-action", complex_actions))
    if code:
        score += 0.32 if len(code) >= 3 else 0.20
        signals.append(_signal("code", code))
    if technical:
        if len(technical) >= 4:
            score += 0.32
        elif len(technical) >= 2:
            score += 0.20
        else:
            score += 0.10
        signals.append(_signal("technical", technical))
    if reasoning:
        score += 0.38 if len(reasoning) >= 2 else 0.18
        signals.append(_signal("reasoning", reasoning))
    if decision:
        score += 0.24 if len(decision) >= 2 else 0.16
        signals.append(_signal("decision", decision))
    if multi_step:
        score += 0.05
        signals.append(_signal("multi-step", multi_step))
    if constraints:
        if len(constraints) >= 4:
            score += 0.18
        elif len(constraints) >= 2:
            score += 0.11
        else:
            score += 0.05
        signals.append(_signal("constraints", constraints))
    if deliverables:
        if len(deliverables) >= 3:
            score += 0.20
        elif len(deliverables) >= 2:
            score += 0.13
        else:
            score += 0.06
        signals.append(_signal("deliverables", deliverables))
    if evaluation:
        if len(evaluation) >= 3:
            score += 0.18
        elif len(evaluation) >= 2:
            score += 0.11
        else:
            score += 0.05
        signals.append(_signal("evaluation", evaluation))
    if scale:
        score += 0.16
        signals.append("scale requirement")
    if composition or clause_count >= 3:
        score += 0.05
        signals.append(_signal("composite", composition) if composition else "composite clauses")
    if question_count > 2:
        score += 0.04
        signals.append(f"{question_count} questions")

    tier = _tier_for_score(
        score=score,
        simple=simple,
        medium_actions=medium_actions,
        complex_actions=complex_actions,
        code=code,
        technical=technical,
        reasoning=reasoning,
        decision=decision,
        constraints=constraints,
        deliverables=deliverables,
        evaluation=evaluation,
        scale=scale,
        tokens=tokens,
    )
    return ChineseComplexityResult(
        tier=tier,
        score=round(max(-1.0, min(1.0, score)), 3),
        signals=tuple(signals),
    )


def estimate_mixed_tokens(text: str) -> int:
    cjk_count = len(CJK_RE.findall(text))
    non_cjk_count = len(CJK_RE.sub("", text))
    return max(1, round(cjk_count * 0.8 + non_cjk_count / 4))


def _tier_for_score(
    *,
    score: float,
    simple: list[str],
    medium_actions: list[str],
    complex_actions: list[str],
    code: list[str],
    technical: list[str],
    reasoning: list[str],
    decision: list[str],
    constraints: list[str],
    deliverables: list[str],
    evaluation: list[str],
    scale: list[str],
    tokens: int,
) -> Tier:
    if _is_reasoning(
        reasoning,
        decision,
        technical,
        code,
        medium_actions,
        complex_actions,
        constraints,
        deliverables,
        evaluation,
        tokens,
    ):
        return Tier.REASONING

    if (
        complex_actions
        and (
            code
            or len(technical) >= 2
            or len(deliverables) >= 2
            or len(constraints) >= 2
            or (len(complex_actions) >= 2 and technical)
        )
    ) or (code and technical):
        return Tier.COMPLEX

    if (scale and len(constraints) >= 2) or (len(deliverables) >= 3 and len(constraints) >= 2):
        return Tier.COMPLEX

    # Short definition-style technical questions are usually not complex enough for
    # the stronger models, even when they contain terms like "数据库" or "架构".
    if (
        simple
        and not (
            complex_actions or code or reasoning or decision or constraints or deliverables or scale
        )
        and tokens <= 32
    ):
        if len(technical) <= 2:
            return Tier.SIMPLE
        return Tier.MEDIUM

    if score >= 0.40:
        return Tier.COMPLEX
    if score >= 0.15:
        return Tier.MEDIUM
    return Tier.SIMPLE


def _is_reasoning(
    reasoning: list[str],
    decision: list[str],
    technical: list[str],
    code: list[str],
    medium_actions: list[str],
    complex_actions: list[str],
    constraints: list[str],
    deliverables: list[str],
    evaluation: list[str],
    tokens: int,
) -> bool:
    if len(reasoning) >= 2:
        return True
    if decision and len(evaluation) >= 3:
        return True
    if decision and reasoning and (technical or code or medium_actions):
        return True
    diagnostic_actions = {"排查", "调试", "修复", "审计"}
    if reasoning and diagnostic_actions.intersection(complex_actions):
        if technical or code or constraints or len(deliverables) >= 2:
            return True
    if any(word in reasoning for word in ("推导", "证明", "论证", "根因分析")):
        return bool(technical or code or tokens > 40)
    return False


def _has_cjk(text: str) -> bool:
    return bool(CJK_RE.search(text))


def _matches(text: str, keywords: tuple[str, ...]) -> list[str]:
    occupied: list[tuple[int, int]] = []
    matches: list[tuple[int, str]] = []
    for keyword in sorted(keywords, key=len, reverse=True):
        lowered = keyword.lower()
        start = text.find(lowered)
        while start != -1:
            end = start + len(lowered)
            if not any(start < used_end and end > used_start for used_start, used_end in occupied):
                occupied.append((start, end))
                matches.append((start, keyword))
                break
            start = text.find(lowered, start + 1)
    return [keyword for _, keyword in sorted(matches)]


def _signal(label: str, matches: list[str]) -> str:
    return f"{label} ({', '.join(matches[:3])})"

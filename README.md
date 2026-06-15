# pp-router

一个最小可用（MVP）的 LLM 中转网关：一个 query 进来，**按难度自动路由**到不同的模型，返回结果并带上**实际使用的模型**与 **token 用量**。

底座把 [litellm](./litellm) 当作库（`litellm.Router`）做执行引擎，难度分类复用 litellm 内置的 `ComplexityRouter`（纯本地规则、无额外 LLM 调用、<1ms）。

## 当前范围

本期只做两件事：

1. **内置两个模型**（硬编码，暂不做通用注册）：`glm-4.7-flash`（快/免费）与 `glm-5.1`（强），均走智谱 BigModel（OpenAI 兼容端点）。
2. **难度路由**：判难度 → 选模型 → 调用 → 返回 `content / model / usage / routing`。

暂未做（后续规划）：持久化、自有 token 计量单位、`source` 归因、监控看板、流式、运行时注册与热更新。

## 路由规则

难度分级由 `ComplexityRouter.classify()` 给出（7 个维度加权打分 → 难度档），再映射到模型：

| 难度档 | 分数区间（默认） | 模型 |
|---|---|---|
| SIMPLE | `< 0.15` | `glm-4.7-flash` |
| MEDIUM | `0.15 – 0.35` | `glm-4.7-flash` |
| COMPLEX | `0.35 – 0.60` | `glm-5.1` |
| REASONING | `> 0.60` / 出现 ≥2 个推理标记 | `glm-5.1` |

打分维度（权重）：tokenCount(0.10)、codePresence(0.30)、reasoningMarkers(0.25)、technicalTerms(0.25)、simpleIndicators(0.05, 负)、multiStepPatterns(0.03)、questionComplexity(0.02)。只取最后一条 user 消息分类；token 数用 `len//4` 字符估算；词表偏英文。映射表见 `pprouter/config.py` 的 `TIER_MAP`，分类封装见 `pprouter/routing.py`。

## 环境要求

- Python `>=3.10, <3.14`（litellm 约束；本项目用 [uv](https://docs.astral.sh/uv/) 管理，实测 3.13）
- 一个智谱 BigModel API Key

## 安装

```bash
# 1. 配置 key
cp .env.example .env
# 编辑 .env，填入 BIGMODEL_API_KEY=<你的 key>

# 2. 安装依赖（uv 会自动选 3.13 并以 editable 方式装本地 litellm）
uv sync
```

## 运行

```bash
uv run uvicorn pprouter.main:app --host 127.0.0.1 --port 4000
```

## API

### `GET /models` — 列出内置模型

```bash
curl -s http://127.0.0.1:4000/models
```
```json
[
  {"id":"glm-4.7-flash","litellm_model":"openai/glm-4.7-flash","tiers":["SIMPLE","MEDIUM"]},
  {"id":"glm-5.1","litellm_model":"openai/glm-5.1","tiers":["COMPLEX","REASONING"]}
]
```

### `POST /chat` — 自动路由对话

请求体（`query` 与 `messages` 二选一；可选 `model` 强制指定、跳过分类）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `query` | string | 单轮便捷写法，等价于 `messages=[{role:user, content:query}]` |
| `messages` | array | OpenAI 风格 `{role, content}` 列表 |
| `model` | string | 可选，强制用 `glm-4.7-flash` 或 `glm-5.1`，跳过难度分类 |

**简单 query（自动 → glm-4.7-flash）**
```bash
curl -s -X POST http://127.0.0.1:4000/chat \
  -H "Content-Type: application/json" \
  -d '{"query":"2+2=?"}'
```
```json
{
  "content": "4",
  "model": "glm-4.7-flash",
  "routing": {"target_group":"glm-4.7-flash","forced":false,"tier":"SIMPLE","score":-0.1},
  "usage": {"prompt_tokens":9,"completion_tokens":107,"total_tokens":116}
}
```

**复杂 query（自动 → glm-5.1）**
```bash
curl -s -X POST http://127.0.0.1:4000/chat \
  -H "Content-Type: application/json" \
  -d '{"query":"think step by step: analyze the performance implications of implementing Raft for our microservices architecture"}'
```
返回 `routing.tier` 为 `COMPLEX`/`REASONING`、`model` 为 `glm-5.1`。

**强制指定模型（跳过分类）**
```bash
curl -s -X POST http://127.0.0.1:4000/chat \
  -H "Content-Type: application/json" \
  -d '{"query":"hi","model":"glm-5.1"}'
```
`routing.forced` 为 `true`，`tier`/`score` 为 `null`。

## 项目结构

```
pp-router/
├── pprouter/
│   ├── config.py        # 两个内置 GLM、TIER_MAP、API_BASE、key 读取
│   ├── schemas.py       # ChatRequest / ChatResponse 等 pydantic 模型
│   ├── router_engine.py # 由 config 构建 model_list 与 litellm.Router
│   ├── routing.py       # 包装 ComplexityRouter：分类 → 选 model_group
│   ├── api.py           # POST /chat、GET /models
│   └── main.py          # FastAPI app + lifespan 装配
├── litellm/             # 只读依赖（vendored），不修改
├── pyproject.toml
├── .env.example         # BIGMODEL_API_KEY=
└── .gitignore           # 忽略 .env、.venv
```

## 说明与局限

- 接入方式：litellm 无原生 BigModel provider，用 `openai/` 兼容前缀 + `api_base` 调用。成本计算未启用（启动时的 cost-map 警告可忽略）。
- 思考模式：GLM 可能返回 `reasoning_content`；若 `message.content` 为空则回落到 `reasoning_content`。
- 难度分类只看最后一条 user 消息，词表偏英文，中文命中较弱（可在 `complexity_router_config` 自定义词表/边界后改善）。
- 无持久化：模型在 `config.py` 写死，重启即恢复。

## 后续规划

自有 token 计量单位（按 input/output × 每模型系数）、`source` 维度归因、监控看板、动态注册与热更新、流式响应。

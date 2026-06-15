# pp-router

一个最小可用（MVP）的 LLM 中转网关：一个 query 进来，**按难度自动路由**到不同的模型，返回结果并带上**实际使用的模型**与 **token 用量**。

底座把 [litellm](./litellm) 当作库（`litellm.Router`）做执行引擎，难度分类复用 litellm 内置的 `ComplexityRouter`（纯本地规则、无额外 LLM 调用、<1ms）。

## 当前范围

本期只做两件事：

1. **内置两个模型**（硬编码，暂不做通用注册）：`glm-4.7-flash`（快/免费）与 `glm-5.1`（强），均走智谱 BigModel（OpenAI 兼容端点）。
2. **难度路由**：判难度 → 选模型 → 调用 → 返回 `content / model / usage / routing`。

暂未做的能力（持久化、token 计量、看板、流式、中文增强、动态注册等）统一收敛在文末 [Roadmap](#roadmap里程碑制)，按 M1–M3 推进。

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
- 难度分类只看最后一条 user 消息，词表偏英文，中文命中较弱（可在 `complexity_router_config` 自定义词表/边界后改善；见 Roadmap M2）。
- 无持久化：模型在 `config.py` 写死，重启即恢复（见 Roadmap M1）。

## Roadmap（里程碑制）

本项目按里程碑推进，当前处于 **M0（MVP，已完成）**。每个里程碑标注可复用的 litellm 现成能力，避免重复造轮子。

下表为目标排期，自 2026-06-15 起算（假设：单人全职 + AI Coding 加速、跳过周末、含联调/测试 buffer，不含鉴权/部署）；各里程碑细节见下文。

| 里程碑 | 时间窗（2026） | 工作日 | 主要交付 | 验收 |
|---|---|---|---|---|
| **M1** 计量与可观测 | 6/15 一 – 6/19 五 | 5d | 持久化落库 · token 计量单位 · `source` 归因 · `/stats` + 简易看板 | 6/19 |
| **M2** 体验与中文增强 | 6/22 一 – 6/26 五 | 5d | `/chat` 流式（SSE） · 中文分类增强 | 6/26 |
| **M3** 动态化 | 6/29 一 – 7/1 三 | 3d | 运行时注册 · `TIER_MAP` 热更新 | 7/1 |

**全部交付：2026-07-01（周三），约 2.5 周。** 若砍掉 Web 看板（仅留 `/stats`）、M3 只做内存态热更新，可提前至 6/26 收尾（约 2 周）；瓶颈在 M2 中文调参，不建议压。

### M0 — MVP（已完成）

难度自动路由 + 两个内置 GLM，提供 `POST /chat`、`GET /models`，返回实际使用的模型与 token 用量。

### M1 — 计量与可观测（token 计量 + 看板并行）

目标：每次调用可记账、可回看。先打通数据底座，**token 计量与可视化看板在本阶段并行交付**。

- **持久化底座**：接 litellm `CustomLogger` 回调（`Router(optional_callbacks=[...])`），把每次调用的 `StandardLoggingPayload`（usage / model / model_group / tier / 延迟 / metadata）落库（SQLite 起步）。
- **自有 token 计量单位**：在真实 usage 之上按 `input/output × 每模型系数` 折算“自有单位”；成本侧可复用 litellm `completion_cost()` 或 per-deployment 的 `input_cost_per_token` + `output_cost_per_token`（`register_model()`）。
- **`source` 维度归因**：`/chat` 接收可选 `source` 字段 → 经 litellm `metadata={...}` 透传 → 落到 `StandardLoggingMetadata`，作为看板的归因维度。
- **可视化看板**：读库展示用量 / 计量单位 / 成本，按模型 · tier · source 维度统计；先出 `GET /stats` JSON 接口，Web 看板随后。

### M2 — 体验与中文增强

目标：补齐流式响应与中文场景的分类准确度。

- **流式响应**：`/chat` 支持 SSE；底层用 `Router.acompletion(stream=True)` + `stream_options={"include_usage": True}`（或 `stream_chunk_builder` 聚合）拿流式 usage，保证计量在流式下不丢。
- **中文难度分类增强**：通过 `complexity_router_config` 覆盖中文词表与 `token_thresholds` / `tier_boundaries`。⚠️ 这是真实扩展点（非 litellm 现成）：`ComplexityRouter` 现用 `\b` 词边界对中文不生效、`len // 4` 估 token 偏高，需替换中文 token 估算与匹配逻辑。

### M3 — 动态化

目标：去掉硬编码，模型可在运行时管理。

- **运行时注册与热更新**：把 `config.py` 写死的 `BUILTIN_MODELS` / `TIER_MAP` 改为可运行时增删改，复用 `Router` 的 deployment 管理能力，无需重启。

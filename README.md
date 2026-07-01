# pp-router

一个最小可用（MVP）的 LLM 中转网关：一个 query 进来，**按难度自动路由**到不同的模型，返回结果并带上**实际使用的模型**与 **token 用量**。

底座把 [litellm](./litellm) 当作库（`litellm.Router`）做执行引擎，英文/混合英文难度分类复用 litellm 内置的 `ComplexityRouter`，中文场景叠加本项目的本地规则分类器（纯本地规则、无额外 LLM 调用、<1ms）。

## 当前范围

本期只做两件事：

1. **内置四个模型**（硬编码，暂不做通用注册）：`step-3.7-flash`（快/简单）走 StepFun，`glm-4.7`（标准）、`glm-5.1`（强）走智谱 BigModel，`qwen3.7-max`（旗舰/推理）走阿里通义 DashScope（均为 OpenAI 兼容端点，按模型各自配 base/key）。
2. **难度路由**：判难度 → 选模型 → 调用 → 返回 `content / model / usage / routing`。

暂未做的能力（持久化、token 计量、看板、动态注册等）统一收敛在文末 [Roadmap](#roadmap里程碑制)，按 M1–M3 推进。

## 路由规则

难度分级先由 `ComplexityRouter.classify()` 给出（7 个维度加权打分 → 难度档）。当 prompt 含中文时，再由 `pprouter.zh_complexity` 进行中文规则评分；最终取更高的有效难度档，再映射到模型：

| 难度档 | 分数区间（默认） | 模型 |
|---|---|---|
| SIMPLE | `< 0.15` | `step-3.7-flash` |
| MEDIUM | `0.15 – 0.35` | `glm-4.7` |
| COMPLEX | `0.35 – 0.60` | `glm-5.1` |
| REASONING | `> 0.60` / 出现 ≥2 个推理标记 | `qwen3.7-max` |

英文打分维度（权重）：tokenCount(0.10)、codePresence(0.30)、reasoningMarkers(0.25)、technicalTerms(0.25)、simpleIndicators(0.05, 负)、multiStepPatterns(0.03)、questionComplexity(0.02)。中文规则额外识别：定义/翻译等简单问法，解释/总结/对比等中等任务，代码/架构/高并发/数据库/安全等复杂技术任务，以及“一步步/推导/权衡/取舍/选型”等推理决策任务。只取最后一条 user 消息分类；映射表见 `pprouter/config.py` 的 `TIER_MAP`，分类合并见 `pprouter/routing.py`。

## 环境要求

- Python `>=3.10, <3.14`（litellm 约束；本项目用 [uv](https://docs.astral.sh/uv/) 管理，实测 3.13）
- 一个 StepFun API Key（`STEP_API_KEY`）、一个智谱 BigModel API Key（`BIGMODEL_API_KEY`）与一个阿里通义 DashScope API Key（`QWEN_API_KEY`）；三者都需配置，缺任一启动即报错

## 安装

```bash
# 1. 配置 key
cp .env.example .env
# 编辑 .env，填入 STEP_API_KEY=<StepFun key>、BIGMODEL_API_KEY=<智谱 key> 与 QWEN_API_KEY=<通义 key>

# 2. 安装依赖（uv 会自动选 3.13 并以 editable 方式装本地 litellm）
uv sync
```

## 运行

```bash
uv run uvicorn pprouter.main:app --host 127.0.0.1 --port 4000
```

## 前端控制台（React + Tailwind）

`frontend/` 是一个 Vite + React + TS + Tailwind v4 的单页控制台，提供：① 查看支持的模型；② 多轮对话（不持久化，刷新清空），可「自动路由」或指定模型；③ 历史 query 的模型与 token 用量看板。

它通过 Vite dev 代理把 `/api/*` 转发到后端 `:4000`，所以**先起后端，再起前端**：

```bash
# 终端 A：后端（见上）
uv run uvicorn pprouter.main:app --host 127.0.0.1 --port 4000

# 终端 B：前端
cd frontend
npm install      # 首次
npm run dev      # 打开 http://localhost:5173
```

> 注意用 `localhost`（Vite 默认绑 IPv6 `::1`，curl `127.0.0.1` 会连不上）。生产构建用 `npm run build`（产物在 `frontend/dist/`）；部署时需自行把 `/api` 指向后端（dev 代理仅 `npm run dev` 生效）。

## 线上部署（CloudBase）

已部署到 CloudBase 环境 `principleprocrastination-d6cb34f`（ap-shanghai）：

| 角色 | 形态 | 访问地址 |
|---|---|---|
| 前端控制台 | 静态托管（manageApps / webapps） | https://pprouter-web-principleprocrastination-d6cb34f.webapps.tcloudbase.com/ |
| 后端 API | 云托管 CloudRun 容器（`pprouter-api`） | https://pprouter-api-267965-8-1304190584.sh.run.tcloudbase.com |

- 前端构建时通过 `VITE_API_BASE` 注入后端 URL（见 `src/api.ts`）；后端开了 CORS（`allow_origins=["*"]`）以支持跨域。
- 后端容器要点：监听 **80** 端口（CloudBase 不注入 `PORT`，健康检查走 80）；设 `LITELLM_LOCAL_MODEL_COST_MAP=True` 跳过启动时拉远程 cost-map；`0.5C/1G`、`MinNum=1`（常驻 1 实例，省冷启动但会持续占用环境资源点）。
- 凭据：`STEP_API_KEY` / `BIGMODEL_API_KEY` / `QWEN_API_KEY` 当前以 `ENV` 烤进镜像（`cloudrun/` 已 gitignore，不进版本库；镜像为环境私有）。更安全的做法是改用控制台「环境变量」配置（CloudRun 的 `serverConfig.EnvParams`）并删掉 Dockerfile 里那几行后重部署。
- 局限：`history.jsonl` 写在容器本地磁盘，重部署/实例重建会清空（看板用量随之归零）；持久化需接 DB（Roadmap M1）。

### 重新部署

```bash
# 后端（改完 pprouter/ 后，先同步到容器工程再部署）
cp -r pprouter cloudrun/pprouter-api/pprouter
npx mcporter call cloudbase.manageCloudRun action=deploy serverName=pprouter-api \
  targetPath="$PWD/cloudrun/pprouter-api" serverType=container \
  serverConfig='{"OpenAccessTypes":["PUBLIC"],"Cpu":0.5,"Mem":1,"MinNum":1,"MaxNum":1}' --output json

# 前端（注入后端 URL 本地构建后直传 dist）
cd frontend && VITE_API_BASE="https://pprouter-api-267965-8-1304190584.sh.run.tcloudbase.com" npm run build && cd ..
npx mcporter call cloudbase.manageApps action=deployApp serviceName=pprouter-web \
  filePath="$PWD/frontend/dist" framework=static installCmd='' buildCmd='' --output json
```

> mcporter 配置在 `config/mcporter.json`（含 `cwd` 指向仓库根，使 targetPath 校验通过）；首次需 `npx mcporter call cloudbase.auth action=start_auth authMode=device` 登录并 `set_env`。

## API

### `GET /models` — 列出内置模型

```bash
curl -s http://127.0.0.1:4000/models
```
```json
[
  {"id":"step-3.7-flash","litellm_model":"openai/step-3.7-flash","tiers":["SIMPLE"]},
  {"id":"glm-4.7","litellm_model":"openai/glm-4.7","tiers":["MEDIUM"]},
  {"id":"glm-5.1","litellm_model":"openai/glm-5.1","tiers":["COMPLEX"]},
  {"id":"qwen3.7-max","litellm_model":"openai/qwen3.7-max","tiers":["REASONING"]}
]
```

### `POST /chat` — 自动路由对话

请求体（`query` 与 `messages` 二选一；可选 `model` 强制指定、跳过分类）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `query` | string | 单轮便捷写法，等价于 `messages=[{role:user, content:query}]` |
| `messages` | array | OpenAI 风格 `{role, content}` 列表 |
| `model` | string | 可选，强制用 `step-3.7-flash` / `glm-4.7` / `glm-5.1` / `qwen3.7-max`，跳过难度分类 |

**简单 query（自动 → step-3.7-flash）**
```bash
curl -s -X POST http://127.0.0.1:4000/chat \
  -H "Content-Type: application/json" \
  -d '{"query":"2+2=?"}'
```
```json
{
  "content": "4",
  "model": "step-3.7-flash",
  "routing": {"target_group":"step-3.7-flash","forced":false,"tier":"SIMPLE","score":-0.1},
  "usage": {"prompt_tokens":9,"completion_tokens":107,"total_tokens":116}
}
```

**四档自动路由示例（下表 `tier`/`score`/`model` 均为本地分类实测结果）**

| tier | score | 路由模型 | 示例 `query` |
|---|---|---|---|
| `SIMPLE` | `-0.10` | `step-3.7-flash` | `2+2=?` |
| `MEDIUM` | `+0.20` | `glm-4.7` | `how does database indexing improve query performance?` |
| `COMPLEX` | `+0.43` | `glm-5.1` | `implement a concurrent rate limiter in python: needs threading, a queue, and must handle high throughput without race conditions on the shared counter` |
| `REASONING` | `+0.38` | `qwen3.7-max` | `think step by step: analyze the performance trade-offs of Raft vs Paxos for our distributed system, and evaluate the pros and cons` |
| `MEDIUM` | `+0.35` | `glm-4.7` | `解释一下数据库索引为什么能加速查询` |
| `COMPLEX` | `+0.48` | `glm-5.1` | `帮我设计一个高并发订单系统，包含缓存、限流、数据库分库分表` |
| `REASONING` | `+0.97` | `qwen3.7-max` | `一步步分析我们应该用 Raft 还是 Paxos，并说明取舍` |

> `REASONING` 的触发条件是 score > 0.60 **或**命中 ≥2 个 reasoning marker——上例 score 仅 0.38，但同时命中 `step by step` 与 `evaluate`，故判为 REASONING。

复杂 query 实跑一条（自动 → glm-5.1）：
```bash
curl -s -X POST http://127.0.0.1:4000/chat \
  -H "Content-Type: application/json" \
  -d '{"query":"implement a concurrent rate limiter in python: needs threading, a queue, and must handle high throughput without race conditions on the shared counter"}'
```
返回 `routing.tier` 为 `COMPLEX`、`model` 为 `glm-5.1`。

**强制指定模型（跳过分类）**
```bash
curl -s -X POST http://127.0.0.1:4000/chat \
  -H "Content-Type: application/json" \
  -d '{"query":"hi","model":"glm-5.1"}'
```
`routing.forced` 为 `true`，`tier`/`score` 为 `null`。

### `POST /chat/stream` — 流式对话（SSE）

请求体与 `/chat` 完全一致，返回 `text/event-stream`。前端控制台默认走此端点：强模型的长推理边生成边下发，不会被网关在 ~60s 处 504 截断。事件类型：

| `type` | 含义 |
|---|---|
| `routing` | 首个事件，携带本次路由（`target_group`/`tier`/`score`/`forced`） |
| `reasoning` | 思考内容增量（仅上游返回 thinking 时出现；前端显示「推理中…」，不计入正文） |
| `delta` | 答案正文增量（逐字拼接） |
| `done` | 结束事件，携带最终 `model` 与 `usage`（据此记历史） |
| `error` | 上游出错（如限流），以事件下发，前端显示为「请求失败」 |

上游静默时服务端每 15s 发一个 `: ping` 心跳保活；响应头带 `X-Accel-Buffering: no` 禁用网关缓冲，保证即时下发。

```bash
curl -sN -X POST http://127.0.0.1:4000/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"query":"think step by step: 分析在微服务里引入 Raft 的性能影响"}'
```

### `GET /history` — 历史请求看板

每次成功的 `/chat` 都会追加一条记录（query / 实际模型 / tier / token 用量 / 时间）到 JSONL 文件（`history.jsonl`，已 gitignore）。本接口读回历史并附带汇总。

| query 参数 | 默认 | 说明 |
|---|---|---|
| `limit` | `50` | 返回最近 N 条明细（`items`，最新在前）；`summary` 始终基于全部记录 |

```bash
curl -s "http://127.0.0.1:4000/history?limit=20"
```
```json
{
  "summary": {
    "total_requests": 3,
    "total_tokens": 3739,
    "by_model": {
      "step-3.7-flash": {"requests": 1, "total_tokens": 171},
      "glm-4.7": {"requests": 1, "total_tokens": 3283},
      "qwen3.7-max": {"requests": 1, "total_tokens": 285}
    }
  },
  "items": [
    {"ts":"2026-06-22T16:45:29+08:00","query":"say hi in one word","model":"qwen3.7-max","tier":null,"forced":true,"score":null,"usage":{"prompt_tokens":15,"completion_tokens":270,"total_tokens":285}}
  ]
}
```

> 这是 Roadmap **M1** 的最小落地版（JSON 文件 + 看板接口）；尚未做 `source` 归因、成本/自有单位折算、Web 看板。

## 项目结构

```
pp-router/
├── pprouter/
│   ├── config.py        # 四个内置模型（含 per-model api_base/api_key_env）、TIER_MAP、key 读取
│   ├── schemas.py       # ChatRequest / ChatResponse 等 pydantic 模型
│   ├── router_engine.py # 由 config 构建 model_list 与 litellm.Router
│   ├── routing.py       # 合并 LiteLLM 英文分类 + 中文分类：分类 → 选 model_group
│   ├── zh_complexity.py # 本地中文难度分类规则
│   ├── history.py       # HistoryStore：JSONL 落盘 + 读回（历史看板）
│   ├── api.py           # POST /chat、POST /chat/stream(SSE)、GET /models、GET /history
│   └── main.py          # FastAPI app + lifespan 装配
├── frontend/            # React + Tailwind 控制台（Vite，/api 代理到 :4000）
│   └── src/             # api.ts + App + ChatPanel/ModelsPopover/HistoryPanel
├── litellm/             # 只读依赖（vendored），不修改
├── history.jsonl        # 运行时生成的请求历史（gitignore）
├── pyproject.toml
├── .env.example         # STEP_API_KEY= / BIGMODEL_API_KEY= / QWEN_API_KEY=
└── .gitignore           # 忽略 .env、.venv、history.jsonl
```

## 说明与局限

- 接入方式：litellm 无原生 StepFun / BigModel / 通义 provider，统一用 `openai/` 兼容前缀 + 各模型自己的 `api_base`/`api_key` 调用（`step-3.7-flash` → StepFun `https://api.stepfun.com/v1`，GLM → 智谱 BigModel，`qwen3.7-max` → 阿里通义 DashScope `compatible-mode`）。成本计算未启用（启动时的 cost-map 警告可忽略）。
- 思考模式：除 `qwen3.7-max` 推理档外，普通聊天档会尽量关闭或降低思考强度以保持响应速度：GLM 4.7/5.1 通过 `extra_body={"thinking":{"type":"disabled"}}` 关闭 thinking；`step-3.7-flash` 不支持完全关闭 reasoning，改为 `extra_body={"reasoning_effort":"low"}`。若非流式响应的 `message.content` 为空，仍回落到 `reasoning_content`。
- 难度分类只看最后一条 user 消息；中文已加本地规则增强，但仍是启发式分类，后续需要用真实线上样本持续调关键词、权重和边界。
- 持久化：请求历史已落 `history.jsonl`（`GET /history` 看板，M1 最小版）；但模型清单仍在 `config.py` 写死，重启即恢复（动态注册见 Roadmap M3）。

## Roadmap（里程碑制）

本项目按里程碑推进，当前处于 **M0（MVP，已完成）**。每个里程碑标注可复用的 litellm 现成能力，避免重复造轮子。

下表为目标排期，自 2026-06-15 起算（假设：单人全职 + AI Coding 加速、跳过周末、含联调/测试 buffer，不含鉴权/部署）；各里程碑细节见下文。

| 里程碑 | 时间窗（2026） | 工作日 | 主要交付 | 验收 |
|---|---|---|---|---|
| **M1** 计量与可观测 | 6/15 一 – 6/19 五 | 5d | 持久化落库 · token 计量单位 · `source` 归因 · `/stats` + 简易看板 | 6/19 |
| **M2** 体验优化 | 6/22 一 – 6/26 五 | 5d | `/chat` 流式（SSE） · 中文分类调参 | 6/26 |
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

### M2 — 体验优化

目标：补齐流式响应，并基于真实样本持续调优中文场景的分类准确度。

- **流式响应**：`/chat` 支持 SSE；底层用 `Router.acompletion(stream=True)` + `stream_options={"include_usage": True}`（或 `stream_chunk_builder` 聚合）拿流式 usage，保证计量在流式下不丢。
- **中文难度分类调参**：当前已通过 `pprouter.zh_complexity` 叠加中文本地规则，后续用真实 query 样本继续调关键词、权重、token 估算与边界；不直接修改 vendored `litellm/`。

### M3 — 动态化

目标：去掉硬编码，模型可在运行时管理。

- **运行时注册与热更新**：把 `config.py` 写死的 `BUILTIN_MODELS` / `TIER_MAP` 改为可运行时增删改，复用 `Router` 的 deployment 管理能力，无需重启。

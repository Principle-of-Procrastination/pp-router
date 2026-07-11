# pp-router

一个基于 FastAPI、LiteLLM 和 React 的 LLM 路由网关。请求会按难度路由到不同模型，支持流式输出、中文复杂度分类、用量统计和 CloudBase 部署。

## 模型与路由

| 难度 | 模型 | 说明 |
|---|---|---|
| `SIMPLE` | `step-3.7-flash` | 简短问答、定义、翻译 |
| `MEDIUM` | `glm-4.7` | 解释、总结、普通技术问题 |
| `COMPLEX` | `glm-5.1` | 实现、架构、调试、复杂技术任务 |
| `REASONING` | `glm-5.1` | 推导、论证、决策权衡；保留模型默认思考能力 |

英文分类复用 LiteLLM `ComplexityRouter`，中文由 `pprouter.zh_complexity` 做本地规则增强。中文分类除任务词外，还识别约束密度、复合交付物、规模指标、诊断任务和多维决策；短追问如“继续”“基于这个再详细一点”会继承上一条用户任务的上下文。

## 公开访问边界

- `/models`、`/chat`、`/chat/stream`、`/history` 无需登录；仓库不再提供访问密钥或会话接口。
- CORS 只允许显式来源；生产默认不公开 OpenAPI 和 Swagger UI。
- 聊天同时受单 IP 与全局滑动窗口限流，读取接口也有限流；模型调用有全局并发、单次输入、输出 token 和总时长上限。
- 上游错误只向客户端返回稳定错误码和 request ID，详细异常写入 CloudRun 日志。
- 历史记录在服务端保留最近用户 query 的前 1000 字符，但公开 `/history` 会清空 query，只返回模型、难度和 token 统计；CloudBase 集合权限为 `ADMINONLY`。

## 本地运行

要求 Python `>=3.10,<3.14`、Node.js 22+ 和 [uv](https://docs.astral.sh/uv/)。

```bash
cp .env.example .env
# 填入 STEP_API_KEY、BIGMODEL_API_KEY

uv sync
uv run uvicorn pprouter.main:app --host 127.0.0.1 --port 4000
```

没有配置 `CLOUDBASE_ENV_ID` / `CLOUDBASE_API_KEY` 时，历史记录使用本地 `history.db`。两者必须同时提供，否则服务拒绝启动。

前端：

```bash
cd frontend
npm ci
npm run dev
```

Vite 将 `/api/*` 代理到 `127.0.0.1:4000`。打开 `http://localhost:5173` 即可使用。

## 配置

| 环境变量 | 必需 | 默认 | 说明 |
|---|---:|---|---|
| `STEP_API_KEY` | 是 | - | StepFun 上游凭据 |
| `BIGMODEL_API_KEY` | 是 | - | 智谱上游凭据 |
| `CORS_ORIGINS` | 否 | 本地与线上控制台 | 逗号分隔的精确 origin，禁止 `*` |
| `CHAT_REQUESTS_PER_MINUTE` | 否 | `30` | 单 IP 每分钟聊天上限 |
| `GLOBAL_CHAT_REQUESTS_PER_MINUTE` | 否 | `120` | 单实例每分钟聊天总上限 |
| `READ_REQUESTS_PER_MINUTE` | 否 | `120` | 单 IP 每分钟历史读取上限 |
| `MAX_CONCURRENT_REQUESTS` | 否 | `4` | 上游模型并发上限 |
| `MAX_OUTPUT_TOKENS` | 否 | `4096` | 单次最大输出 token |
| `UPSTREAM_TIMEOUT_SECONDS` | 否 | `180` | 单次上游总时长 |
| `CLOUDBASE_ENV_ID` | 生产 | - | CloudBase 环境 ID |
| `CLOUDBASE_API_KEY` | 生产 | - | 仅服务端使用的 NoSQL API key |
| `CLOUDBASE_HISTORY_COLLECTION` | 否 | `pprouter_history` | 历史集合名 |

## API

```bash
curl -sS http://127.0.0.1:4000/models

curl -sS -X POST http://127.0.0.1:4000/chat \
  -H 'Content-Type: application/json' \
  -d '{"query":"解释一下数据库索引为什么能加速查询"}'

curl -sSN -X POST http://127.0.0.1:4000/chat/stream \
  -H 'Content-Type: application/json' \
  -d '{"query":"帮我设计一个高并发订单系统"}'
```

流事件包括 `routing`、`reasoning`、`delta`、`done` 和 `error`。上游静默时每 15 秒发送注释心跳，但不会取消 pending 模型读取。

`GET /history?limit=50` 的 `limit` 范围为 1–100，汇总由 CloudBase 聚合查询完成，公开响应不包含原始 query。

## 测试

```bash
uv run ruff check pprouter tests
uv run pytest -q

cd frontend
npm test
npm run build
```

根目录 GitHub Actions 对后端和前端执行相同检查。

## CloudBase 部署

当前资源：

| 角色 | 资源 | 地址 |
|---|---|---|
| 前端 | `pprouter-web` Web 应用 | https://pprouter-web-principleprocrastination-d6cb34f.webapps.tcloudbase.com/ |
| 后端 | `pprouter-api` CloudRun | https://pprouter-api-267965-8-1304190584.sh.run.tcloudbase.com |
| 历史 | NoSQL `pprouter_history` | `ADMINONLY`，索引 `ts_desc` / `model_asc` |

CloudRun 直接从仓库根目录的 `Dockerfile` 构建，`requirements.txt` 由 `uv.lock` 生成。部署必须通过 `serverConfig.EnvParams` 注入以下 secret，禁止写进 Dockerfile：

- `STEP_API_KEY`
- `BIGMODEL_API_KEY`
- `CLOUDBASE_API_KEY`

非 secret 配置包括 `CLOUDBASE_ENV_ID=principleprocrastination-d6cb34f`、集合名和精确 CORS origin。后端部署完成后，以 `VITE_API_BASE` 注入后端 URL 构建并更新现有 `pprouter-web` 应用。

## 结构

```text
pprouter/                      FastAPI、路由、分类、安全与历史存储
frontend/                      React/Vite 控制台
tests/                         后端单元与协议回归测试
specs/production-hardening/    本轮需求、设计与任务追踪
specs/public-access-refresh/   公开访问与分类器升级说明
Dockerfile                     CloudRun 唯一容器入口
requirements.txt               uv 锁定依赖导出
```

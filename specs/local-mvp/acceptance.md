# 验收状态

用户提供官方 API 凭证后，已完成本地 MVP 和 P4 真实验收。凭证仅写入本地 `.env`（权限 0600、Git 忽略），未写入源码或前端。

- [x] 新 SQLite 迁移、WAL、本地启动、幂等 pp_admin 初始化。
- [x] 管理员会话 / CSRF、公司应用、密钥签发 / 轮换 / 撤销、内部开户凭证。
- [x] OpenAI SDK 普通 / 流式接入、两家适配参数、reasoning_content、图片 / JSON / 工具协议。
- [x] 权限能力过滤、分类失败降级、同环境工具模型及模式绑定。
- [x] 分类 / 执行 / 重试分别入账，未知不记零，取消与重启恢复，月末边界和 CSV。
- [x] 四个管理页面、真实浏览器的开户到月报流程、桌面和移动端截图检查。
- [x] 30 条标注任务、默认模拟上游、显式真实 smoke 和路由评测命令。
- [x] 两家官方 API 账号真实可用性、全部 pp_admin 真实闭环。
- [x] 真实语义路由命中率 >=90%，真实硬约束满足率 100%。

固定 30 条标注任务中，真实分类命中可接受路线 30/30，能力和权限约束满足 30/30。这是当前标注集的验收结果，不代表任意任务的泛化准确率。

## 本次本地检查（2026-11-05）

- pytest：77 项通过，包含 30 条标注任务的硬约束测试、真实本地 HTTP 断线、并发开户幂等、只选路预览，以及真实验收脚本的模拟运行。
- Vitest：4 项通过。
- Chromium：1 项端到端通过，覆盖开户、授权、密钥、调试、月报 / CSV、模型页面与移动端。
- TypeScript / Vite 构建、Ruff、Alembic schema check、Git whitespace check 通过。
- 无上游凭证时，实际本地服务健康检查、pp_admin 登录和未配置状态显示通过。
- 启动 / 退出检查通过；退出后 4000 / 5173 及测试端口关闭，无遗留子进程。

## 真实验收与消耗

- 三个首发模型文本、显式 / auto、两家图片 / 流式 / 工具往返、JSON Object、严格 JSON Schema 全部通过。
- 修复真实联调发现的 DeepSeek 工具调用 `index` 扩展字段：接受 SDK 原样回传，转发上游时移除响应专用位置字段；保留 `reasoning_content`。
- 真实第二家公司验证请求体冒充被拒、请求头不能改变归属、分公司月报一致、开户凭证与应用密钥互斥、停用和撤销立即生效。临时公司已停用、密钥已撤销。
- 30 条语义评测只运行正式选路链路，跳过业务生成；分类消耗照常持久化。路由预览请求的实际执行模型为空，并标记 `execution_skipped`，不会伪装成完成业务回答。
- 验收总计 46 个请求、47 次上游调用，确认输入 10,679、输出 1,364、总计 **12,043 token**，未知用量 **0**。其中 30 条分类评测消耗 8,931 token。
- 常规生成上限降为 256 token，工具轮次上限 512；遇到兼容问题后使用断点续跑，避免重复已经通过的图片、JSON 和文本场景。

| 实际模型 | 阶段 | 调用数 | 输入 token | 输出 token | 总 token |
|---|---|---:|---:|---:|---:|
| deepseek-flash | 路由分类 | 31 | 8,356 | 861 | 9,217 |
| deepseek-flash | 业务执行 | 9 | 1,217 | 120 | 1,337 |
| deepseek-v4-pro | 业务执行 | 1 | 9 | 36 | 45 |
| kimi-k3.1-pro | 业务执行 | 6 | 1,097 | 347 | 1,444 |

本地证据（均无密钥或模型正文）：`.local/provider-preflight.json`、`.local/live-smoke.json`、`.local/routing-evaluation.json`、`.local/live-isolation.json`、`.local/live-acceptance-summary.json`。月报包含所有这些真实上游消耗；这是 token 统计，不是供应商结算金额。

## Lighthouse Docker Compose 验收（2026-11-05）

- 已部署到用户指定的 Lighthouse，升级后的配置为 4 核 / 4 GB / 60 GB；网关和 Nginx 使用 Docker Compose，后端单进程、非 root、只读根文件系统，SQLite 独立持久化。
- 公网 HTTPS 可信证书、HTTP 跳转和证书自动续期通过；Certbot dry-run 成功。仅对外开放 80 / 443，后端 4000 不映射至宿主机；保留原有 SSH 防火墙规则。
- 服务器独立初始化 `pp_admin`。上游密钥通过一次性公钥加密传输，挂载为只读文件，不出现在镜像或容器环境元数据中。初始化凭证加密取回后仅保存在本机 `.local/lighthouse-credentials.json`（0600），未在日志或聊天中显示。
- 公网登录、Secure / HttpOnly / SameSite Cookie、CSRF、Origin、未授权拒绝、身份字段冒充与两类密钥互斥检查通过。
- 为控制上线验收费用，仅运行 3 个业务请求、4 次上游调用：DeepSeek 文本，Kimi 流式 + 图片 + 严格 JSON Schema，以及一次真实 `auto` 语义路由。
- 确认输入 **581**、输出 **59**、总计 **640 token**，未知用量 **0**；路由开销 **289 token**，分类与业务分别计量，月报及 CSV 对账一致。未重复本地的全量真实评测。
- 重建网关容器后，管理员、应用授权及 640 token 用量均保留。真实 Chromium 公网登录、四个管理页面、CSV 下载、移动端布局和退出通过，无页面异常。

部署说明见 `deploy/README.md`；验收证据位于 `.local/lighthouse-acceptance.json`、`.local/lighthouse-usage.csv`、`.local/lighthouse-dashboard.png` 和 `.local/lighthouse-mobile.png`。服务器数据库与本地验收数据库独立，不合并两次验收统计。

## 文档与接入示例检查（2026-11-05）

- 按仓库开发者、其他 PP 套件接入研发、内部运营与销售整理独立指南，补齐 API、环境地址和部署运维说明。
- 文档中的 33 个 API 方法与当前 FastAPI 路由一致；60 个本地文档链接和锚点、21 个 Python / Shell 代码块、5 个请求 JSON 示例通过静态或 schema 校验。
- 独立 Python 示例通过真实网关代码、临时 SQLite 和模拟供应商验证：文本、流式、图片、严格 JSON、工具往返共 6 个业务请求，工具推理字段和模型绑定保留，用量为 180 个模拟 token。
- 使用文档请求体验证公司与授权幂等、签发和撤销密钥、两类凭证不能互用。Node.js 示例通过模拟 fetch 检查请求路径、身份头、trace 和输出上限；示例 Ruff 与文档 whitespace 检查通过。
- 本次只校验文档和示例，不重新部署，不运行真实供应商调用，不改变本地开发或服务器用量。上述模拟 token 不计入真实验收消耗。

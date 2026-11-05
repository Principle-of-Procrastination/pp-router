# pp-router

PP 产品套件共用的多公司 LLM 网关。套件后台通过统一接口调用 DeepSeek、Kimi 官方模型，网关识别公司与应用、执行模型选择，并记录可核对的 token 用量。

**开通公司 → 授权应用 → 签发调用密钥 → 指定模型或 `auto` → 查看用量与月报。**

## 按角色阅读

| 你要做什么 | 从这里开始 |
|---|---|
| 开发、测试或维护这个仓库 | [开发者指南](docs/development.md) |
| 为 PP 的其他套件接入模型调用 | [套件接入指南](docs/integration.md) |
| 向客户介绍产品、申请开户或处理用量问题 | [运营与销售指南](docs/operations.md) |
| 查询字段、权限、错误码、开户接口 | [API 参考](docs/api-reference.md) |
| 找管理端、API 地址和凭证获取方式 | [环境与访问入口](docs/environments.md) |
| 部署、升级、备份或排查服务器 | [Docker Compose 运维手册](deploy/README.md) |
| 查看已通过的测试和真实验收结果 | [验收记录](specs/local-mvp/acceptance.md) |

## 当前能力

- 公司与应用隔离；应用密钥绑定公司、应用、环境，支持有效期、轮换及撤销。
- OpenAI compatible **Chat Completions**：文本、图片、流式响应、工具调用和模型支持的 JSON 输出。
- 显式指定模型，或由 `auto` 先做权限与能力过滤，再进行语义选路。
- 分类和业务执行分别记录用量；按公司、应用、环境、密钥、模型、阶段查看月报及导出 CSV。
- PP 内部管理端、内部开户 API；本地开发与 Docker Compose 单机部署。

当前登记模型为 `deepseek-flash`、`deepseek-v4-pro`、`kimi-k3.1-pro`。可用性由配置、启停、授权及具体请求共同决定，详见 [API 参考](docs/api-reference.md)。

## 先明确三个边界

1. **公司开户不等于创建客户登录账号。** 客户使用 PP 套件自己的账号；pp-router 管理端目前只供内部管理员使用。
2. **本轮只统计 token，不计算金额。** 没有价格、余额、充值、支付、发票、自动扣费或金额预算控制；月报不是供应商结算账单。
3. **这是单机、单后端进程的 MVP。** SQLite 和进程内限流不支持直接扩成多副本；也未提供客户自助门户、细分管理员角色、SSO 或高可用部署。

## 本地快速启动

需要 macOS / Linux、Python 3.12 或 3.13、uv、Node.js 22.12+ 和 npm。

```sh
make setup
make init
make dev
```

管理端位于 `http://127.0.0.1:5173`，API 基础地址为 `http://127.0.0.1:4000/v1`。首次初始化的 `pp_admin` 密码及演示应用密钥写入 `.local/credentials.json`，仅在初始化时生成；该文件不进入 Git。`pp_admin` 管理员和同名演示公司是两个独立实体。

没有上游密钥也能启动和登录管理端。真实调用前，在本地 `.env` 配置 `DEEPSEEK_API_KEY`、`MOONSHOT_API_KEY` 并重启后端；未配置时不会自动返回模拟结果。详细步骤、配置项和故障处理见 [开发者指南](docs/development.md)。

```sh
make test     # 模拟上游：后端、前端、构建和浏览器检查
make release  # 生成不含密钥、数据库的 Docker 部署包
```

真实 smoke 和语义评测会消耗供应商 token，只在明确需要时执行，见 [验证说明](docs/development.md#测试与验收)。

## 文档维护约定

本文档描述当前代码与已验证行为，不把规划写成已上线功能。当前环境信息最后核验于 **2026-11-05**；地址变化集中更新 [环境说明](docs/environments.md)。

修改接口时同步更新 [API 参考](docs/api-reference.md) 与 [接入示例](docs/examples/README.md)；修改产品能力或操作流程时同步更新 [运营与销售指南](docs/operations.md)。历史设计与验收保存在 `specs/`，日常使用以这些角色指南和当前接口实现为准。

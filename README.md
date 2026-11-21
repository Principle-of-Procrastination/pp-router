# pp-router

PP 产品套件共用的多公司 LLM 网关。套件后台通过统一接口调用 DeepSeek、Kimi 官方模型，网关识别公司与应用、执行模型选择，并记录可核对的 token 用量。

Suite 员工用企业账号登录。平台管理员在 Suite 开公司、设席位和开通产品，Router 接收授权、限制调用并按公司记录 token。[Suite 企业管理](https://150.158.155.100:8546/platform)

## 按角色阅读

| 你要做什么 | 从这里开始 |
|---|---|
| 开发、测试或维护这个仓库 | [开发者指南](docs/development.md) |
| 为 PP 的其他套件接入模型调用 | [套件接入指南](docs/integration.md) |
| 核对助理、Code、表格公式等调用记在哪个应用 | [应用目录与用量归属](docs/applications.md) |
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

Suite 的助理和办公侧栏记在 `pp_chat`，桌面 Code 记在 `pp_code`，表格公式记在 `pp_sheets`。`pp_cad` 是另行登记的 Router 产品。每家公司的具体授权、模型和限额在 Router 查看。[应用目录](docs/applications.md)

## 账号和月报

员工账号和席位在 Suite 管理。Router 的 `pp_admin` 可登录网关管理台，也可登录 Suite 的企业管理页。Router 中同名的演示公司只用于记录调用。每月按公司、应用和环境导出已确认的 token 用量，金额在线下核算。

Router 以单个后端进程运行，使用 SQLite 保存数据，在进程内执行限流。运维和恢复按本仓库的 Compose 手册操作。[运维手册](deploy/README.md)

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

服务地址和入口集中维护在环境说明中。历史版本和验收时间保存在验收记录中。[环境说明](docs/environments.md)

修改接口时同步更新 [API 参考](docs/api-reference.md) 与 [接入示例](docs/examples/README.md)；修改产品能力或操作流程时同步更新 [运营与销售指南](docs/operations.md)。历史设计与验收保存在 `specs/`，日常使用以这些角色指南和当前接口实现为准。

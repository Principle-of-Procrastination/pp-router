# PP 套件应用目录

[返回项目首页](../README.md) · [套件接入指南](integration.md) · [环境与地址](environments.md)

平台运营和产品开发者用本页判断一条请求应记在哪个产品下。模型请求的公司、应用和环境从调用凭据取得。企业成员和席位由 Suite 管理。[Suite 企业管理](https://150.158.155.100:8546/platform)

| 来源 | Router 应用 | 什么时候产生用量 |
| --- | --- | --- |
| PP 助理，含文档、演示、表格的助理侧栏 | `pp_chat` | 员工对话、使用助理功能时 |
| Suite 版 PP Code | `pp_code` | 已连接的员工设备调用模型时 |
| PP 表格 | `pp_sheets` | 运行 `PP.AI` 公式时 |
| 单独接入的 PP CAD | `pp_cad` | CAD 客户端通过自己的授权调用时 |

从内容提取记忆的模型请求计入来源产品。打开文件和授予产品访问权限本身不会产生模型用量。Router 初始化预置 `pp_code`、`pp_chat` 和 `pp_cad`。上海 Suite 另行注册了 `pp_sheets`，新环境需要先登记这一产品，再同步购买了表格授权的公司。

网关总上下文上限为 256000 token，默认输出上限为 32000。可用模型、授权限额和剩余上下文共同决定一个请求能否执行。[接口限制](api-reference.md#输出与总上下文上限)

## 从早期演示目录升级

Alembic 数据迁移在现有应用记录上更新代码、名称和业务说明：

| 旧应用 | 新应用 |
|---|---|
| `agent` / 工具调用 | `pp_code` / PP Code |
| `chat` / 普通对话 | `pp_chat` / PP Chat |
| `vision` / 图片理解 | `pp_cad` / PP CAD |

应用 ID、公司应用授权 ID、密钥值、有效期、环境标签、工具续接绑定和历史请求不变。历史用量仍关联原应用 ID，因此报表和 CSV 会按新应用代码显示原有用量，不复制或清零记录。默认演示密钥的显示名称同步更新；自定义密钥名称保留。

升级不会重新发放邀请码或重置密码。若数据库中同时存在旧代码和对应的新代码，迁移会停止并要求维护者先核对，不能自动合并两个不同身份。其他自建应用不受这次更名影响。

应用更名迁移 `6b5d9182c4fa` 保留原有所有调用限制。后续独立迁移 `c7218f4b0ad6` 将现有模型统一为上下文 256000 / 输出 32000，将现有公司应用授权的输出上限统一为 32000，并为发生变更的授权递增策略版本、记录审计。路由策略、模型权限、RPM、并发、启停状态、密钥和历史用量保留。

## PP Code 的已有接入

Suite 员工使用企业账号配对本机启动器，Suite 服务端为这次请求选择本公司 `pp_code` 授权。下表供员工和 Code 维护者查找产品说明。

| 要查看的内容 | PP Code 仓库入口 |
|---|---|
| 安装、启动、连接 Suite 账号和共享项目 | [Code 使用指南](https://github.com/Principle-of-Procrastination/pp-code/blob/main/pp/WEB.md) |
| 本地后端、Credential 存储及模型接入 | [开发者指南 `pp/DEVELOPMENT.md`](https://github.com/Principle-of-Procrastination/pp-code/blob/main/pp/DEVELOPMENT.md) |
| 公开部署参数模板 | [`pp/.env.web.example`](https://github.com/Principle-of-Procrastination/pp-code/blob/main/pp/.env.web.example) |
| 构建、发布变量及客户端发版 | [发布指南 `pp/RELEASING.md`](https://github.com/Principle-of-Procrastination/pp-code/blob/main/pp/RELEASING.md) |
| 发布构建的 CI 实现 | [`.github/workflows/pp-release.yml`](https://github.com/Principle-of-Procrastination/pp-code/blob/main/.github/workflows/pp-release.yml) |

仍在维护的独立 npm 客户端沿用应用邀请码。在旧版的 Sign in 中输入邀请码后，本地后端会验证并保存该公司应用的密钥。旧 `agent` 更名为 `pp_code` 时沿用原密钥和已有用量。

**PP Code 维护者必须同步以下公开部署配置并重新构建发布：**

```dotenv
PP_ROUTER_CONTEXT_TOKENS=256000
PP_ROUTER_OUTPUT_TOKENS=32000
```

同步上述配置模板、本地 `pp/.env.local` 和发布 CI 变量，连同相关文档、测试一起更新，再按 PP Code 发布指南重新构建并发布客户端。已发布二进制内置部署参数，单独修改运行环境不会覆盖这些内置值。旧版发送的 32768 会返回 HTTP 400，网关不提供旧值兼容或静默缩小输出。客户端还应根据新窗口提前压缩长会话；网关不会截掉输入来满足上下文限制。本次网关更新不包含 PP Code 客户端发布。

其他套件通过公司应用密钥确定归属，不在模型请求体里传应用代码。调用方如果额外保存了 `agent/chat/vision` 字符串用于展示或本地查表，应按 [应用代码迁移映射](#从早期演示目录升级)更新；保存应用 ID 的系统无需迁移 ID。

早期 Router 初始化导出的应用字段为 `applications.pp_code`、`applications.pp_chat` 和 `applications.pp_cad`。历史导出文件升级字段名时沿用既有应用 ID 和密钥。

## 新客户开通

Suite 客户由平台管理员在「企业管理」创建公司、设席位、指定企业管理员、开通产品。Suite 自动同步 Router 授权，企业管理员可随即开员工账号。确认公司授权同步后，做一次短调用，在月报中核对公司、产品和 `production` 环境。[企业管理](https://150.158.155.100:8546/platform) · [运营手册](operations.md)

直接使用 Router API 的客户在网关建立公司、申请独立的产品授权和环境密钥。公司记录用于归集用量。Router 平台管理员账号单独管理。[服务端接入](integration.md)

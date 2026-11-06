# PP 套件应用目录

[返回项目首页](../README.md) · [套件接入指南](integration.md) · [环境与地址](environments.md)

PP 的产品套件按 **PP Code、PP Chat、PP CAD** 三个应用登记。应用代表产品归属，不代表模型能力类别；三个应用都可以显式调用全部已登记模型，也都支持 `auto`。

2026-11-06 已在本地和团队服务器完成应用目录迁移（`20261106-01`）。现有 PP Code 邀请码已通过模型目录验证，无需更换；当前发布版本以 [环境说明](environments.md) 为准。

| 应用 | 应用代码 | 业务说明 | 默认输出上限 | 总上下文上限 |
|---|---|---|---:|---:|
| PP Code | `pp_code` | 编程、代码审查、工程理解及开发工具协作 | 32000 | 256000 |
| PP Chat | `pp_chat` | 对话、问答、写作、摘要及通用 AI 助手 | 32000 | 256000 |
| PP CAD | `pp_cad` | CAD 绘图、图纸理解及设计辅助 | 32000 | 256000 |

三者的初始模型权限均包含 `deepseek-flash`、`deepseek-v4-pro`、`kimi-k3.1-pro`，没有按产品设置模型白名单差异。模型需要已启用且供应商已配置；图片、工具、JSON Schema 等请求仍须满足模型自身能力。开通网关应用不代表对应产品已经上线。

初始化 `pp_admin` 时，路由默认模型为 PP Chat 使用 DeepSeek Flash，PP Code / PP CAD 使用 Kimi。它们只是分类降级时的默认偏好；`auto` 仍按能力和任务选择模型，显式指定任一合格模型都可调用。通过开户 API 新建授权时，省略策略则默认使用 DeepSeek Flash，可以显式配置产品偏好。

32000 / 256000 是网关统一配置，不是供应商原生容量声明。总上下文包含输入和预留输出；默认输出 32000 时，输入需在剩余 224000 的预算内。网关使用保守检查，实际可提交内容还受图片、工具等开销影响，详见 [API 限制](api-reference.md#输出与总上下文上限)。管理员仍可把某一授权的输出上限调低。

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

PP Code 的真实仓库为 [Principle-of-Procrastination/pp-code](https://github.com/Principle-of-Procrastination/pp-code)。客户端的使用、开发和发布步骤以该仓库文档为准，本页说明它与 pp-router 的应用归属、凭证和调用约束。

| 要查看的内容 | PP Code 仓库入口 |
|---|---|
| 安装、启动、邀请码录入和更新 | [用户指南 `pp/WEB.md`](https://github.com/Principle-of-Procrastination/pp-code/blob/main/pp/WEB.md) |
| 本地后端、Credential 存储及模型接入 | [开发者指南 `pp/DEVELOPMENT.md`](https://github.com/Principle-of-Procrastination/pp-code/blob/main/pp/DEVELOPMENT.md) |
| 公开部署参数模板 | [`pp/.env.web.example`](https://github.com/Principle-of-Procrastination/pp-code/blob/main/pp/.env.web.example) |
| 构建、发布变量及客户端发版 | [发布指南 `pp/RELEASING.md`](https://github.com/Principle-of-Procrastination/pp-code/blob/main/pp/RELEASING.md) |
| 发布构建的 CI 实现 | [`.github/workflows/pp-release.yml`](https://github.com/Principle-of-Procrastination/pp-code/blob/main/.github/workflows/pp-release.yml) |

PP Code 已使用 `pp_admin` 下原 `agent` 应用的密钥接入。升级后该密钥归属显示为 **PP Code**，已有邀请码、网关地址和本地 Credential 存储继续有效。用户在 PP Code 的 Sign in 入口输入该应用密钥，由 PP Code 本地后端验证并保存；这不是 pp-router 管理员登录，也不代表给每位用户创建了公司账号。同一邀请码的用量仍归属同一个公司应用。

**PP Code 维护者必须同步以下公开部署配置并重新构建发布：**

```dotenv
PP_ROUTER_CONTEXT_TOKENS=256000
PP_ROUTER_OUTPUT_TOKENS=32000
```

同步上述配置模板、本地 `pp/.env.local` 和发布 CI 变量，连同相关文档、测试一起更新，再按 PP Code 发布指南重新构建并发布客户端。已发布二进制内置部署参数，单独修改运行环境不会覆盖这些内置值。旧版发送的 32768 会返回 HTTP 400，网关不提供旧值兼容或静默缩小输出。客户端还应根据新窗口提前压缩长会话；网关不会截掉输入来满足上下文限制。本次网关更新不包含 PP Code 客户端发布。

其他套件通过公司应用密钥确定归属，不在模型请求体里传应用代码。调用方如果额外保存了 `agent/chat/vision` 字符串用于展示或本地查表，应按 [应用代码迁移映射](#从早期演示目录升级)更新；保存应用 ID 的系统无需迁移 ID。

凭证导出文件统一使用 `applications.pp_code/pp_chat/pp_cad`；验收脚本只读取当前产品代码。本机 `.local/credentials.json` / `.local/lighthouse-credentials.json` 的属性名已一次性更新，密钥值和 ID 保持不变。其他执行机如有旧导出文件，将应用属性名改为当前产品代码即可，不需要重新发钥。

## 新客户开通

按客户创建公司，然后在共享目录中选择需要开通的产品。同一客户购买多个套件时，分别创建对应应用授权和密钥；不为每个客户重复登记产品，也不共用 PP Code 的邀请码接入 PP Chat / PP CAD，以便准确统计归属和独立撤销。

按当前产品配置为三个应用授权全部模型；如后续确有客户限定供应商等特殊要求，再单独调整该客户授权。正式客户使用自己的公司记录，`pp_admin` 保留为内部使用身份。

新增公司只创建用量归属，不创建管理员账号或客户密码。默认 `pp_admin` 之所以既能管理平台又能发起演示调用，是初始化分别创建了管理员和同名公司；权限不来自公司名称。

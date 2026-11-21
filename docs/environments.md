# 环境与访问入口

[返回项目首页](../README.md) · [套件接入](integration.md) · [部署运维](../deploy/README.md)

最后核验：2026-11-06。以下是团队当前环境，不是为客户承诺的永久域名或服务等级。接入时用配置保存地址，避免写死在业务代码中。

## 地址

| 用途 | 本地开发 | 当前团队服务器 |
|---|---|---|
| 管理端 | `http://127.0.0.1:5173/` | <https://150.158.155.100/> |
| Suite 企业管理 | 使用 Suite 平台的本地地址 | [企业管理](https://150.158.155.100:8546/platform) |
| Suite 员工账号与记忆 | 使用 Suite 平台的本地地址 | [账号与记忆](https://150.158.155.100:8546/account) |
| OpenAI SDK `base_url` | `http://127.0.0.1:4000/v1` | `https://150.158.155.100/v1` |
| 模型列表 | `http://127.0.0.1:4000/v1/models` | `https://150.158.155.100/v1/models` |
| 内部开户根地址 | `http://127.0.0.1:4000/internal/v1` | `https://150.158.155.100/internal/v1` |
| 管理 API 根地址 | `http://127.0.0.1:4000/admin/v1` | `https://150.158.155.100/api/admin/v1` |
| 健康检查 | `http://127.0.0.1:4000/health` | `https://150.158.155.100/health` |
| Swagger / OpenAPI | `http://127.0.0.1:4000/docs`、`/openapi.json` | 当前 Nginx 未单独公开这两个入口 |

服务器的 `/api/` 是管理端反向代理前缀，会在转发后端时移除。套件模型调用统一使用 `/v1`；不要把管理端页面地址或 `/api/admin/v1` 填进 OpenAI SDK 的 `base_url`。

健康检查成功表示网关和数据库可访问。`providers` 中的 `true` 仅表示配置了对应凭证，不证明供应商账户额度、具体模型可用性或供应商实时健康。

## 账号和凭证由谁提供

| 凭证 | 本地开发 | 上海团队服务器 |
| --- | --- | --- |
| 平台管理员 | `make init` 首次生成开发账号。 | 有权限的同事从私有运维手册取得登录资料。 |
| 公司应用调用密钥 | 使用初始化时的测试密钥，或到管理台签发。 | Suite 为购买产品的公司自动配置。直接接入的客户由服务端负责人领取。 |
| 内部开户凭证 | 初始化生成，或由管理员签发。 | 网关负责人交给受信任的 Suite 平台服务。 |

`make init` 保留已有账号和密钥。需要恢复管理权限时，按运维手册处理。[凭证维护](../deploy/README.md#凭证维护)

## 团队服务器管理员登录

内部平台管理员使用 `pp_admin` 登录 Router 管理台和 Suite 企业管理页。登录资料保存在私有 pp-suite 仓库的上海运维手册。Suite 企业管理员和员工使用自己的企业账号。[Router 管理台](https://150.158.155.100/) · [企业管理](https://150.158.155.100:8546/platform) · [内部平台管理员登录资料](https://github.com/Principle-of-Procrastination/pp-suite/blob/main/deploy/production/README.md#平台管理员)

## 环境隔离

本地和服务器使用独立数据库，账号密码、公司内部 ID、授权 ID、调用密钥和用量互不通用。把本地密钥换一个 API 地址不会自动变成服务器密钥。

密钥上的 `environment` 是**调用归因标签和工具续接隔离条件**，例如 `local`、`staging`、`production`。它不会切换网关地址、创建数据库、改变上游供应商或创建独立限流额度。初始演示密钥即使在服务器上运行，标签也仍是 `local`；正式接入应新建自己的公司应用密钥并明确环境。

## 当前部署记录

- Lighthouse：上海，实例 `lhins-pjwgqizk`，公网 IP `150.158.155.100`，升级后 4 核 / 4 GB / 60 GB。
- Docker Compose 项目：`pp-router`；常驻容器为 `gateway`、`web`。
- 发布入口：`/opt/pp-router/current`；持久化配置与数据：`/opt/pp-router/shared`。
- 当前运行版本在服务器的 `/opt/pp-router/current` 和实际容器镜像中查看。Router 记录 Suite 的助理、Code 和表格公式用量。[应用目录](applications.md)
- 后端端口只在容器网络内使用，公网由 Nginx 提供 HTTPS；证书续期 timer 为 `pp-router-cert-renew.timer`。
- 首次上线验收消耗 640 token；2026-11-06 的应用目录及上限迁移只查询身份、模型目录和报表，没有新增模型调用。详细范围和证据见 [验收记录](../specs/local-mvp/acceptance.md)。

调整地址、证书、访问入口或服务器目录时，同步更新本页，并通知所有已接入套件的负责人。

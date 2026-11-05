# Docker Compose 单机部署

[返回项目首页](../README.md) · [开发者指南](../docs/development.md) · [当前环境与地址](../docs/environments.md)

服务器使用两个常驻容器：`gateway`（单进程 FastAPI + SQLite）和 `web`（Nginx + 管理端静态文件）。`certbot` 只在申请、续期证书时运行。无需在服务器安装 Python、Node.js、uv 或运行 Vite；本地开发仍使用 `make dev`。

以下服务器命令由有权管理该部署的维护者执行，需要 Docker Compose 和相应文件权限；涉及共享目录、systemd 的步骤通常以 root 执行。文档中的示例值需替换为本次发布信息，不要把“首次启动”重跑到已有数据库上。客户端不需要执行本页任何步骤。

## 发布与目录

在开发机器执行 `make release`，输出 `.local/deploy/pp-router.tar.gz` 和 SHA256。打包使用白名单，不包含 `.env`、数据库、初始化凭证、Git 或开发依赖。构建前端并从 `uv.lock` 导出带哈希的 `deploy/requirements.lock`，镜像安装时校验依赖哈希。

```text
/opt/pp-router/releases/<release>/    发布源码、Dockerfile、Compose 和前端构建产物
/opt/pp-router/current               当前发布的符号链接
/opt/pp-router/shared/compose.env    发布版本和持久化目录等非敏感设置
/opt/pp-router/shared/gateway.env    上游密钥和网关设置，UID 10001、0400
/opt/pp-router/shared/data/          持久化 SQLite，UID 10001、0700
/opt/pp-router/shared/nginx.conf     当前 Nginx 配置
/opt/pp-router/shared/letsencrypt/    ACME 账户和证书，root 管理
/opt/pp-router/shared/acme/          HTTP-01 验证目录
```

`compose.env` 示例：

```dotenv
PPROUTER_RELEASE=20261105-01
PPROUTER_STATE_DIR=/opt/pp-router/shared
```

如果服务器访问 PyPI 较慢，可在 `compose.env` 增加 `PPROUTER_PIP_INDEX_URL=https://mirrors.cloud.tencent.com/pypi/simple`，使用[腾讯云官方软件源](https://cloud.tencent.com/document/product/213/8623)。安装仍严格校验锁文件中的版本与 SHA256，不禁用 TLS 校验。

`gateway.env` 示例：

```dotenv
DEEPSEEK_API_KEY=实际密钥
MOONSHOT_API_KEY=实际密钥
PPROUTER_DATABASE_PATH=/data/pprouter.db
PPROUTER_ALLOWED_ORIGINS=https://实际域名或IP
PPROUTER_COOKIE_SECURE=true
PPROUTER_TIMEOUT_SECONDS=180
PPROUTER_ROUTER_TIMEOUT_SECONDS=5
PPROUTER_MAX_CONCURRENT=16
```

密钥文件以只读文件挂载进容器，不写入镜像或 Compose 环境变量。后端使用 UID 10001、只读根文件系统、独立写入目录，不映射宿主机端口；只有 Nginx 的 80/443 对外开放。发布前检查现有服务，不覆盖其他应用和防火墙规则。

## 首次启动

先确认 80 / 443 端口与当前目录没有其他服务占用，并允许外部访问 HTTPS 及证书 HTTP-01 验证端口。通过已有的受控服务器管理通道上传发布包，核对开发机生成的 SHA256，再用 `tar -xzpf pp-router.tar.gz -C 新发布目录` 解压并保留代码目录权限。

建立共享目录：data 属于 UID / GID 10001、权限 0700；gateway.env 属于 10001、权限 0400。Nginx 和证书目录由 root 管理。填写两个环境文件，把 `current` 符号链接指向新发布目录。注意挂载源 gateway.env、nginx.conf 必须是文件，不能让 Docker 因源文件缺失而创建同名目录。

下面的辅助函数只指定 Compose 文件和非敏感参数文件；后续每个新终端先执行这一段：

```sh
cd /opt/pp-router/current
dc() {
  docker compose --env-file /opt/pp-router/shared/compose.env -f deploy/compose.yaml "$@"
}
```

构建并初始化独立服务器数据库：

```sh
dc build
dc run --rm --no-deps gateway \
  python -m pprouter.cli init --credentials-file /data/initial-credentials.json
```

初始化创建独立服务器数据库、`pp_admin` 管理员及三个演示应用，不复制开发数据。首次凭证使用 `0600`，应通过安全通道保存到本机受保护位置，随后从服务器删除。重复初始化不重置密码或密钥。演示应用的初始环境标签为 `local`，正式应用应在管理端签发对应环境的独立密钥。

首先把 `nginx-bootstrap.conf` 复制到共享的 `nginx.conf`，启动容器；此时 80 端口只接受证书验证，其余路径返回 503，不能提交登录凭证：

```sh
dc up -d
```

证书使用已有域名或 IP 地址。IP 证书要求支持 `--ip-address` 和 `shortlived` 的 Certbot（webroot 方式至少 5.4），参考 [Let's Encrypt 官方说明](https://letsencrypt.org/2026/03/11/shorter-certs-certbot/)。先用 staging 验证 HTTP-01，配置到独立测试目录；成功后申请可信证书到正式目录。不要把 staging 证书作为正式交付。

```sh
dc run --rm certbot certonly \
  --non-interactive --agree-tos --register-unsafely-without-email \
  --preferred-profile shortlived --webroot -w /var/www/acme --ip-address 实际IP
```

将 `nginx-https.conf.template` 的 `${PUBLIC_HOST}` 替换为实际域名或 IP，其他 Nginx 变量保持不变，保存至共享的 `nginx.conf`。如果在原文件上写入，执行 `dc exec -T web nginx -t`，成功后 `dc exec -T web nginx -s reload`；如果通过替换文件改变了 inode，应重建 web 容器以重新挂载配置。80 跳转 HTTPS，443 同源提供管理端和 API：

- 管理端：`https://实际域名或IP/`
- 标准 OpenAI SDK：`https://实际域名或IP/v1`
- 管理端的 `/api/` 由代理去掉前缀；内部开户使用 `/internal/v1/`。
- SSE 关闭代理缓冲和压缩；20 MiB 请求体上限，210 秒代理读超时。

安装 `pp-router-cert-renew.service`、`pp-router-cert-renew.timer` 到 `/etc/systemd/system/`，执行 `systemctl daemon-reload` 和 `systemctl enable --now pp-router-cert-renew.timer`。此 timer 每天两次检查是否需要续期并重新加载 Nginx；应用本身由 Docker Compose 的重启策略管理。IP 证书有效期较短，必须验证续期流程。

## 状态检查与低成本验收

从当前发布目录定义好上述 `dc` 函数后执行：

```sh
dc ps
dc logs --tail 100 gateway web
dc exec -T web nginx -t
systemctl status pp-router-cert-renew.timer
journalctl -u pp-router-cert-renew.service --since '7 days ago' --no-pager
```

从客户端检查 `https://实际域名或IP/health`。health 成功及 providers 已配置，不代表供应商额度充足或所有模型可用。若返回 HTML，检查是否误用了未代理的路径；服务器管理 API 带 `/api` 前缀，完整地址见 [环境表](../docs/environments.md)。

先检查页面、健康接口、管理员登录、CSRF、模型目录、未授权拒绝和月报；这些操作不产生模型费用。上线只做少量短输入和低输出上限的真实调用，然后核对公司、请求、上游调用与确认 token，不重复全量真实评测。

普通页面查询不会收费；调试台“执行”和“仅预览 auto 路由”会发起真实上游调用。可先使用 [独立接入示例](../docs/examples/README.md)中的一个短场景验证，不能把示例全部运行当成无成本健康检查。

## 凭证维护

| 需要处理的凭证 | 处理方式 |
|---|---|
| 公司应用密钥 | 管理端签发 / 撤销；平滑更新先签发新钥、部署调用方、验证后撤销旧钥 |
| 内部开户凭证 | 仅供可信 PP 后台；管理员签发 / 撤销，不能交给客户 |
| DeepSeek / Kimi 密钥 | 通过受控运维通道修改 shared/gateway.env；不放入镜像、命令行参数或前端 |
| 管理员密码 | 当前团队共享账号见[环境文档](../docs/environments.md#团队服务器管理员登录)；其他部署使用各自的首次凭证，初始化命令不会重置已有密码 |

后台“轮换”会立即撤销旧钥，并继承旧钥的有效期；需要并存切换或延长有效期时应另行签发。调用密钥不是供应商密钥，两者的更新方式不同。

修改 gateway.env 后保持 UID / GID 10001 和权限 0400，使用容器重建确保替换后的文件重新挂载：

```sh
dc up -d --no-deps --force-recreate gateway
dc ps
```

重建不删除 `/data`，但应安排在允许短暂中断的维护窗口。不要把配置内容、初始化凭证或 Cookie 输出到部署日志。服务器重建后核对健康及现有报表；无需为了验证读取新配置而跑完整真实评测。

目前没有自助密码重置界面、重置 CLI 或管理员账号管理 API。管理员密码遗失时，由仓库维护者在备份和维护窗口中执行针对该账号的恢复：使用项目的 Argon2 哈希方法更新密码，并清理该管理员的既有会话。不要写入明文密码，也不要删除数据库后重新初始化。通过授权凭证共享方式交接新密码；恢复工具的新增应经过代码审阅和隔离测试。

## 备份

当前没有自动数据库备份任务，需由运维设置备份周期与保存位置。TLS timer 只负责证书，不备份用量。备份含密码哈希、调用记录和配置凭证，应限制访问并加密保存到另一个受控位置。

维护窗口可采用下面的停机一致性备份；它会短暂停止模型调用。以 root 从当前发布目录执行，先定义 `dc`：

```sh
(
  set -eu
  umask 077
  PP_BACKUP_DIR="/opt/pp-router/backups/$(date -u +%Y%m%dT%H%M%SZ)"
  mkdir -p "$PP_BACKUP_DIR"
  chmod 700 "$PP_BACKUP_DIR"
  readlink /opt/pp-router/current > "$PP_BACKUP_DIR/release-path.txt"
  dc stop gateway
  trap 'dc start gateway' EXIT
  cp -a /opt/pp-router/shared/data "$PP_BACKUP_DIR/data"
  cp -a /opt/pp-router/shared/compose.env /opt/pp-router/shared/gateway.env \
    /opt/pp-router/shared/nginx.conf /opt/pp-router/shared/letsencrypt "$PP_BACKUP_DIR/"
)
dc ps
```

备份目录保留原数据和文件权限。不要直接复制运行中的 SQLite 主文件而遗漏 WAL；需要不停机备份时，应使用经过验证的 SQLite backup API 流程。定期在隔离环境验证恢复，避免恢复测试同时运行两个后端连接同一个数据库。

## 升级与回滚

1. 在开发机通过所需测试并运行 `make release`；记录新发布标签及包 SHA256。
2. 上传并解压到新的 releases 子目录。保持线上 current 不变，使用新目录的 Compose 文件和显式 `PPROUTER_RELEASE=新标签` 构建镜像；不要覆盖仍在使用的标签。
3. 进入维护窗口，停止 gateway，完成上述一致性备份并保存旧路径、配置和镜像。升级备份时暂不执行示例中的自动启动，直到新版本准备完成。
4. 修改 shared/compose.env 的发布标签，把 current 切换为新发布的符号链接。重新 `cd /opt/pp-router/current`，定义 `dc`，执行 `dc up -d`。后端启动会应用 Alembic 迁移；确认目录仍是原 shared/data。
5. 核对容器健康、HTTPS、管理员登录、原有公司与用量、模型目录及证书 timer。只有本次变更涉及真实协议时，才追加小样本真实调用。

回滚先停止新网关，保留故障状态和数据库副本，再恢复旧发布路径、标签与配置。如果新版本执行过不兼容迁移，需要一起恢复停机备份，而不能只切镜像；恢复旧数据库会丢失备份后写入的请求和管理改动，必须先评估并保留相关记录。恢复 data 时保持 UID / GID 10001 及权限，不能把旧 WAL 与另一份数据库主文件混合。

常规停止用 `dc stop`，不要删除 shared 数据。数据库只允许一个后端进程，不能启用多 worker 或扩容 gateway 副本。需要换 IP / 域名时同步修改证书、Nginx、允许的 Origin 和 [环境说明](../docs/environments.md)，并通知所有调用方。

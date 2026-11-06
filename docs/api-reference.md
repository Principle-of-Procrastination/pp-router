# API 参考

[返回项目首页](../README.md) · [套件接入指南](integration.md) · [环境地址](environments.md)

本文以当前 FastAPI 路由和 Pydantic schema 为准。只支持列出的 Chat Completions 子集，不是完整 OpenAI API 实现；未提供 Responses、Embeddings、语音、视频、图像生成、文件上传或 Batch 接口。

## 地址与身份

下表中的路径是后端逻辑路径。当前服务器的管理 API 需添加 `/api` 前缀，例如登录为 `POST https://150.158.155.100/api/admin/v1/auth/login`；模型和内部开户 API 使用表中路径即可。本地直连 4000 端口无需 `/api`。

| 接口族 | 身份 | 用途 |
|---|---|---|
| `/v1/*` | 应用 Bearer 密钥，通常 `ppk_` 前缀 | 当前密钥绑定的公司应用调用 |
| `/internal/v1/*` | 内部开户 Bearer 凭证，通常 `ppi_` 前缀 | 可信后台开户、授权、签发及撤销应用密钥 |
| `/admin/v1/*` | 管理员会话 Cookie；写操作还需 CSRF | 全平台管理 |
| `/health` | 无 | 数据库连通与供应商配置状态 |

前缀不是鉴权依据，服务器校验密钥哈希、类型、启停及有效期。内部开户凭证目前是跨公司的平台级能力，未细分公司 / 应用权限。管理员会话同样没有只读销售或运营角色。

管理员 `pp_admin` 与公司 `pp_admin` 分属 `admin_users`、`companies`，不存在“同名公司自动获得管理权限”的规则。创建公司、开通应用或发放应用密钥都不会创建管理员账号。当前没有客户后台登录或管理员账号管理 API；停用公司影响它的应用调用，不会停用独立的管理员账号。

共享产品代码为 `pp_code`、`pp_chat`、`pp_cad`，均默认授权全部模型。开户接口需要的 `application_id` 是管理员提供的数据库 ID，不是应用代码；模型调用的归属只从密钥解析。

## 模型调用

### `GET /v1/models`

返回该应用密钥可访问、模型已启用且对应供应商凭证已配置的模型；有可用模型时加入 `auto`。返回的是 OpenAI 风格 `{ "object": "list", "data": [...] }`，不是供应商实时可用性探测，也不包含针对某一请求的全部能力过滤结果。

各条目除 `id/object/created/owned_by` 外，还提供扩展字段 `context_tokens`（总上下文上限）与 `max_output_tokens`（模型、当前授权和服务共同允许的输出上限）。当前默认分别为 256000 / 32000；`auto` 取当前目录中最保守的上限，便于客户端配置会话窗口。查询不会调用供应商模型。

### `POST /v1/chat/completions`

请求 JSON，未知顶层字段被拒绝。可选参数省略时由网关或供应商使用默认值。

| 字段 | 当前约束 |
|---|---|
| `model` | 必填；`auto` 或已登记的模型 ID |
| `messages` | 必填；1–200 条消息 |
| `stream` | 默认 `false` |
| `stream_options.include_usage` | 默认 `false`；只允许与 `stream=true` 一起使用 |
| `n` | 仅 `1` |
| `max_tokens` / `max_completion_tokens` | 二选一，整数 1–32000；还须满足授权和模型上限，超限拒绝；均省略则使用授权上限 |
| `temperature` | 0–2；最终适用性取决于模型 / 模式 |
| `top_p` | 大于 0 且不超过 1 |
| `stop` | 字符串或 1–16 个字符串组成的数组 |
| `tools` | 1–64 个 function 工具；名称唯一，参数需为合法 JSON Schema |
| `tool_choice` | `auto`、`none`、`required` 或指定 function；除 `none` 外需提供 tools |
| `response_format` | `text`、`json_object` 或带 `json_schema` 的 `json_schema` |
| `reasoning_effort` | `none/minimal/low/medium/high/xhigh/max`；受下面的模型规则限制 |
| `thinking` | DeepSeek 扩展：`{"type":"enabled"}` / `{"type":"disabled"}`；SDK 可通过 `extra_body` 传递 |
| `user` | 可选匿名化用户标识，最多 128 字符；用于公司范围内哈希归因，不作为鉴权或会话 ID |

请求头 `X-Trace-ID` 可选，1–128 个字符，允许字母、数字、`_`、`.`、`:`、`-`。它不提供幂等或去重功能。不要把姓名、邮箱或完整业务内容塞进 trace。

消息 `role` 支持 `system/developer/user/assistant/tool`，`developer` 转发上游时映射为 `system`。`content` 可为文本；`user` / `tool` 可使用文本与图片的 content 数组。`tool` 必须带 `tool_call_id`。assistant 工具调用消息可使用 `content=null`，并保留 `tool_calls` 和 `reasoning_content`。

文本与图片混合示例：

```json
{
  "model": "auto",
  "messages": [{
    "role": "user",
    "content": [
      {"type": "text", "text": "请描述这张图片。"},
      {"type": "image_url", "image_url": {"url": "https://images.example.com/sample.png", "detail": "auto"}}
    ]
  }],
  "max_tokens": 256
}
```

示例图片地址是占位地址，运行时替换为供应商可访问的图片。也可使用 `data:image/png;base64,...`；省略号不是有效图片。内联 MIME 支持 PNG / JPEG / WebP / GIF，单张解码后最多 5 MiB，总图片数最多 8，总请求体最多 20 MiB。HTTPS URL 不允许用户名密码、localhost、`.local` 主机或显式私有 IP。网关不下载 URL、不附带图片访问认证；还需满足供应商实际图像限制。

### 输出与总上下文上限

所有产品当前统一默认输出 **32000**、总上下文 **256000**。总上下文包含输入和预留输出，并不是输入 256000 后还能再输出 32000。客户端可以请求更低输出；超过 32000 的值返回 HTTP 400 `invalid_request`，不会调用上游。授权或模型上限更低时，超出该上限的模型会被过滤；无合格候选则拒绝，不自动缩小请求值。标准响应 `usage` 仍是实际用量，不是预留额度。

网关在选路和调用前进行保守检查：输入文本 / 推理续接按 UTF-8 字节数计，计入工具定义、工具调用、格式、消息开销，并为每张图片预留 80000，再加上有效输出上限。这不是供应商精确 token 数；实际可接受内容可能小于名义窗口，多张图片也可能先触发上下文限制。该估计只用于保护调用，不记入确认用量。输入过长时拒绝，不裁剪消息或丢弃图片；客户端需缩短内容或压缩历史。

### 模型与模式约束

以下为本项目当前登记与适配行为，不代表供应商未来目录或对所有模型的承诺：

| 模型 | 图片 | 工具 | JSON Object | 严格 JSON Schema | 默认模式 |
|---|---|---|---|---|---|
| `deepseek-flash` | 支持 | 支持 | 支持 | 不支持 | 关闭思考 |
| `deepseek-v4-pro` | 不支持 | 支持 | 支持 | 不支持 | 开启思考；强制工具选择时另受模式规则约束 |
| `kimi-k3.1-pro` | 支持 | 支持 | 支持 | 支持 | 始终推理，默认 `reasoning_effort=low` |

- DeepSeek 可用 `reasoning_effort=none` 关闭思考。`minimal→low`，`medium/xhigh→high`。同时传 thinking 和 effort 时不得冲突。
- Kimi 不接受 `thinking` 或 `reasoning_effort=none`；模式归一化后使用 `low/high/max`。
- Kimi 支持 `tool_choice=required`，当前不支持指定单个函数的强制选择。
- DeepSeek 强制工具选择只允许非思考模式；`tools[].function.strict=true` 所需的独立 beta 端点不在当前接入范围内。
- 图片、工具、格式、输出上限、模式或保守上下文检查不兼容，会使该模型被候选过滤。显式模型因此可能统一返回 `model_unavailable`。
- 工具绑定存在时，续接必须保持原模型和模式。请求中显式改模式会被拒绝。

严格 JSON 输出示例：

```json
{
  "model": "auto",
  "messages": [{"role": "user", "content": "返回一个 JSON 对象，ok 为 true。"}],
  "max_tokens": 256,
  "response_format": {
    "type": "json_schema",
    "json_schema": {
      "name": "result",
      "strict": true,
      "schema": {
        "type": "object",
        "properties": {"ok": {"type": "boolean"}},
        "required": ["ok"],
        "additionalProperties": false
      }
    }
  }
}
```

### 响应与 SSE

普通响应保留 Chat Completions 的 `choices`、`usage` 等字段，`model` 为实际执行模型，`id` 为 `chatcmpl-<网关请求ID>`。响应头 `X-Request-ID` 为不带 `chatcmpl-` 前缀的网关请求 ID。标准 `usage` 只对应最后一次执行调用，不包含分类或其他尝试。

流式使用 `text/event-stream`、标准 `data: {chunk}` 和正常完成时的 `data: [DONE]`。等待期间可能有 `: heartbeat` SSE 注释，需要忽略。请求包含 `include_usage=true` 且取得 usage 时，网关在末尾输出 `choices=[]` 的用量 chunk。`reasoning_content` 为保留的扩展字段，不会拼成最终回答。

流已开始后无法修改 HTTP 状态码；中途失败会发送含 `error` 的 SSE 数据并结束，不保证出现 `[DONE]`。客户端需要检查流异常与完整结束，不能仅看 HTTP 200。断开或异常会保存相应取消 / 失败状态；缺失 usage 单独标记为未知用量，成功请求也可能出现未知用量。

## 内部开户 API

以下示例响应只列核心字段，ID 为示意值。创建成功当前返回 HTTP **200**，不是 201。所有写入均记录审计；未提供任何公开匿名注册接口。

### 公司

`POST /internal/v1/companies`

```json
{"code":"example_customer","name":"示例客户公司","external_id":"pp-org-example-001"}
```

| 字段 | 约束 |
|---|---|
| `code` | 必填，1–64 位字母、数字、下划线或连字符；唯一 |
| `name` | 必填，1–160 字符 |
| `external_id` | 可选，1–160 字符；全局唯一，建议使用 PP 统一公司 ID |

```json
{"id":"company_id_from_server","code":"example_customer","name":"示例客户公司","external_id":"pp-org-example-001","enabled":true}
```

相同 `external_id` 返回已有公司，不修改名称、代码、启停状态。未提供 external_id 时重复 code 会冲突。当前公司更新只支持启停，不支持改名或修改外部 ID。

`PATCH /internal/v1/companies/{id}`：`{"enabled":false}` 或 `{"enabled":true}`。停用影响该公司所有应用的新请求，不会删除数据或保证中止已在执行的请求。

### 应用授权

从 PP Code / PP Chat / PP CAD 的共享目录选择应用并取得 ID。策略里的 `agent`、`vision` 等是任务分类，不是旧应用标识，应保留这些任务键。

`POST /internal/v1/grants`：`company_id` 和 `application_id` 必填，其他字段见下表。示例显式指定完整策略，便于审阅：

```json
{
  "company_id": "company_id_from_server",
  "application_id": "application_id_provided_by_pp",
  "enabled": true,
  "allowed_models": ["deepseek-flash", "deepseek-v4-pro", "kimi-k3.1-pro"],
  "rpm": 60,
  "concurrency": 4,
  "max_output_tokens": 32000,
  "policy": {
    "classifier_model": "deepseek-flash",
    "default_model": "deepseek-flash",
    "fallback_order": ["deepseek-flash", "kimi-k3.1-pro", "deepseek-v4-pro"],
    "task_routes": {
      "general": "deepseek-flash",
      "reasoning": "deepseek-v4-pro",
      "coding": "kimi-k3.1-pro",
      "agent": "kimi-k3.1-pro",
      "vision": "kimi-k3.1-pro",
      "structured": "kimi-k3.1-pro"
    }
  }
}
```

| 字段 | 当前约束 / 默认 |
|---|---|
| `enabled` | 默认 `true` |
| `allowed_models` | 1–3 项，必须来自当前固定目录；默认三种模型 |
| `rpm` | 1–10000；默认 60，按授权计的滚动 60 秒窗口 |
| `concurrency` | 1–128；默认 4，还受全局并发上限限制 |
| `max_output_tokens` | 256–32000；默认 32000；调用时可选择更低值 |
| `policy.classifier_model` | 当前只能为 `deepseek-flash`；未授权 / 不可用时不能调用分类器 |
| `policy.default_model` | 必须在 allowed_models 中，作为合格候选优先顺序的一部分 |
| `policy.fallback_order` | 1–3 个已登记模型；只有满足本次权限与能力约束的模型才可使用 |
| `policy.task_routes` | 六种已知任务类别的模型偏好，传给分类器，非强制映射 |

返回授权对象，其 `id` 即 `grant_id`，并带 `policy_version`。同一公司 + 应用重复创建返回原对象，**不覆盖配置**。

`PUT /internal/v1/grants/{id}` 使用完整授权设置，**不包含 company_id / application_id**。每次更新递增策略版本。此接口不是部分 PATCH：省略的设置会回到 schema 默认值。更新启停、模型或限额时应提交希望保留的完整配置。当前内部 API 不提供 GET 查询授权列表，调用方需保存返回配置，或由管理员核对。

上面的策略是显式示例，不是承诺所有创建路径的默认顺序相同。API 默认 `fallback_order` 为 Flash → V4 Pro → Kimi；初始化演示策略为 Flash → Kimi → V4 Pro。实际以授权返回值为准。

### 密钥

`POST /internal/v1/keys`

```json
{"grant_id":"grant_id_from_server","name":"example-customer-support-prod","environment":"production","expires_at":null}
```

- 内部开户接口必须提供有效 `grant_id`，不能签发新的内部开户凭证。
- `name` 长度 1–80；`environment` 为 1–32 位字母、数字、下划线或连字符，默认 `local`。
- `expires_at` 为将来的 Unix 时间戳，单位**秒**；`null` 表示未设置到期时间，不是毫秒时间戳。
- 返回 `id`、`kind`、`grant_id`、`environment`、`prefix`、状态等，以及仅此时可见的 `secret`。保存 `id` 和 `secret`，不能从 prefix 还原密钥。
- 此操作不幂等；内部接口没有 rotate，管理员才有 rotate 操作。

`POST /internal/v1/keys/{id}/revoke` 无需请求体，返回 `{"ok":true}`。可重复撤销应用密钥；不能借此撤销内部开户凭证。没有“找回原密钥”或重新启用已撤销密钥接口。

## 管理 API 索引

均以 `/admin/v1` 为逻辑前缀；服务器实际 URL 添加 `/api`。全部管理操作均为平台范围，不是公司自助接口。

| 方法与后缀 | 作用 / 请求 |
|---|---|
| `POST /auth/login` | `{"username":"...","password":"..."}`；返回 username、csrf_token 并设置 HttpOnly 会话 Cookie |
| `GET /auth/me` | 当前管理员与 csrf_token |
| `POST /auth/logout` | 删除当前会话 |
| `GET /companies` | 公司列表 |
| `POST /companies`、`PATCH /companies/{id}` | 同内部公司的创建与启停规则 |
| `GET /applications` | 共享应用目录 |
| `POST /applications` | code、name、可选 description（最多 2000 字符） |
| `PATCH /applications/{id}` | `{"enabled":false}` / true；影响所有公司该应用的新调用 |
| `GET /grants` | 公司应用授权列表 |
| `POST /grants`、`PUT /grants/{id}` | 同内部授权创建与完整更新规则 |
| `GET /keys` | 凭证元数据；不返回 secret 或哈希 |
| `POST /keys` | 同密钥签发；管理员省略 grant_id / 传 null 时可签发内部开户凭证 |
| `POST /keys/{id}/revoke` | 管理员可撤销两类凭证 |
| `POST /keys/{id}/rotate` | 原子撤销旧钥并返回新 secret；保留归属、环境和原有效期 |
| `GET /models` | 模型能力、启停及凭证配置状态 |
| `PATCH /models/{id}` | 模型启停，仅接受 enabled |
| `GET /requests` | 支持 company_id、application_id、status、offset；按时间倒序，每页最多 50 条 |
| `GET /requests/{id}` | 单个请求及其 attempts、路由决策、状态、用量和诊断字段 |
| `GET /audit` | 最近 200 条管理审计记录 |
| `POST /playground` | `{"key_id":"...","request":{ChatRequest}}`，使用所选应用密钥身份执行真实调用 |
| `POST /routing/preview` | 同上；只接受 model=auto、stream=false；跳过业务生成，分类仍是真实调用并计量 |
| `GET /reports/monthly`、`GET /reports/monthly.csv` | 月报 JSON / CSV，筛选见下文 |

会话有效期当前为 8 小时。登录需通过 Origin 检查；其余写操作需携带当前会话的 `X-CSRF-Token`，读请求仍需 Cookie。Cookie 在 HTTPS 部署中启用 Secure。登录本身按客户端 IP 限制每 60 秒最多 10 次。

`routing/preview` 返回 `request_id`、`selected_model`、`routing`，其中 `purpose=routing_preview`、`execution_skipped=true`。请求记录的 `actual_model` 为 null；不是一次已经完成的业务回答。该记录仍计入业务请求统计，分类用量照常计入月报。

## 月报查询与解释

两个报表端点支持相同查询参数：

| 参数 | 取值 |
|---|---|
| `month` | `YYYY-MM`；默认当前 `Asia/Shanghai` 月份 |
| `company_id` / `application_id` / `key_id` | 网关内部 ID，不是 code 或密钥明文 |
| `environment` | 密钥环境标签 |
| `provider` | 当前 `deepseek` / `kimi` |
| `model` | 实际执行或分类模型 ID，不是 `auto` |
| `phase` | `routing` / `completion` |

JSON 包含 `month`、`timezone`、`summary`、`rows`、`note`。rows 按公司、应用、环境、供应商、模型、阶段分组；key_id 可筛选，但不是 rows 的独立分组列。

summary 中 `business_requests` 为去重后的业务记录数；`upstream_calls` 为上游尝试数；`request_success/request_failed/request_interrupted` 与 `success_rate` 描述业务请求，`succeeded/failed` 描述上游尝试。未知用量 `usage_unknown` 按上游调用计数。模型 / 阶段筛选后，只纳入匹配上游调用涉及的业务请求，不能把各组 business_requests 再相加。

`input_tokens/output_tokens/total_tokens` 只汇总确认 usage；`cached_tokens/cache_write_tokens/reasoning_tokens/image_tokens` 是可选明细，不额外加到总量。没有有效确认值时可能为 null；CSV 对应空字段不是确认的零。请求可失败但仍有已确认用量，成功也可能没有收到 usage。

报表基于网关持久化请求：鉴权、schema 或准入阶段在建档前被拒绝的请求通常不在其中，不能作为所有 HTTP 访问的审计总数。没有发起上游调用但已建档的失败请求，会影响业务失败统计。

## 错误与重试

网关业务错误格式示意：

```json
{
  "error": {
    "message": "API key is invalid, expired or revoked.",
    "type": "invalid_api_key",
    "code": "invalid_api_key",
    "param": null,
    "request_id": null
  }
}
```

| HTTP | 常见 code | 处理方向 |
|---|---|---|
| 400 | `invalid_request`、`invalid_trace_id` | 检查字段、类型和协议，不应原样重试 |
| 400 | `model_unavailable`、`no_eligible_model` | 检查授权、启停、凭证、能力、模式及上限 |
| 400 | `unknown_tool_binding`、`tool_model_mismatch`、`tool_mode_mismatch` | 恢复原模型 / 模式和完整工具上下文 |
| 400 | `invalid_model`、`invalid_policy`、`invalid_expiry` | 修正管理 / 开户设置 |
| 401 | `invalid_api_key`、`invalid_service_key`、`login_required`、`invalid_credentials` | 检查身份类型、有效期和会话 |
| 403 | `access_disabled`、`forbidden`、`csrf_failed`、`origin_not_allowed` | 恢复正确授权或管理请求上下文 |
| 404 | `not_found` | 检查管理资源 ID |
| 409 | `conflict` | 唯一键冲突；核对现有资源与幂等方式 |
| 413 | `request_too_large` | 减小请求体；Nginx 也可能提前拒绝并返回非 JSON 内容 |
| 429 | `rate_limit_exceeded`、`concurrency_limit`、`upstream_rate_limit` | 区分网关与上游限制；本地限流可带 `Retry-After` |
| 502 | `upstream_credentials_rejected`、`upstream_rejected_request`、`upstream_connection_error`、`upstream_error` | 由维护者检查上游配置与实际请求组合 |
| 503 | `storage_unavailable` | 停止新增调用并排查存储 |
| 504 | `upstream_timeout` | 结果可能未知，不自动重放 |

并非所有反向代理或未知路径响应都使用上述 JSON。鉴权失败、schema 拒绝等建档前错误可能没有 request ID。流式错误在已开始的 SSE 中返回，HTTP 状态不再变化。

网关关闭 SDK 隐式重试，执行最多两次，仅对明确限流拒绝或连接建立失败等安全条件增加一次尝试。显式模型不换模型；auto 的 fallback 不能突破候选约束；超时结果未知或已输出内容后不重试。客户端的额外重试由接入方负责，`X-Trace-ID` 不会阻止重复消耗。

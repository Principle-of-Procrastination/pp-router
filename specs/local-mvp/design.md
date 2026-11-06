# 本地 MVP 设计

此页保留 MVP 的设计依据；开发、接入和操作步骤以 [项目文档入口](../../README.md)、[开发者指南](../../docs/development.md)和 [部署手册](../../deploy/README.md)为准。

## 数据流

```mermaid
flowchart LR
    A[应用 Bearer 密钥] --> B[公司 / 应用 / 环境]
    B --> C[准入及持久化请求]
    C --> D[权限 / 能力 / 凭证过滤]
    D --> E{模型选择}
    E -->|显式或工具绑定| G[上游执行]
    E -->|auto 多候选| F[受限语义分类]
    F --> G
    F --> H[(SQLite 用量)]
    G --> H
    H --> I[管理端月报 / CSV]
```

两个官方供应商使用 AsyncOpenAI；网关控制重试、超时、参数映射与所有计量。分类无法改变应用权限、模型能力或上游地址。DeepSeek 的 `json_object` 与 Kimi 的严格 Schema 能力分别过滤。Kimi 常开推理，通过 reasoning_effort 调节；DeepSeek 可选择模式。

## 表与约束

- `companies` / `applications` / `company_applications`：共享应用目录，唯一公司应用对、授权范围及策略版本。
- `access_keys`：application 与 provisioning 两种互斥类型；应用凭证必须绑定授权，服务凭证禁止绑定授权。
- `admin_users` / `admin_sessions`：与公司实体独立；会话 token 只存哈希。
- `requests` / `attempts`：一次受理和多次路由 / 执行调用；每个 request + ordinal 唯一，每次 attempt 只完成一次。
- `tool_bindings`：grant + environment + tool_call_id 唯一，保存原模型和模式。
- `models` / `audit_logs`：能力和启停状态、管理动作；不存密钥明文及模型正文。

SQLite WAL、外键、5 秒 busy timeout；先落调用意图，再外发。单进程文件锁避免第二个服务错误恢复正在执行的调用。终态写入及流式关闭放在取消保护区，许可释放幂等。

## 路由策略

默认候选三种模型。策略包含默认模型、classifier_model、fallback_order、task_routes。分类固定 JSON 六种任务和六种原因码，严格解析并检查选中模型是否属于候选；默认分类输出 256 token / 5 秒，文本上下文合计上限 8,000 字符。

产品应用为 PP Code / PP Chat / PP CAD，均可调用全部已授权模型；路由类别 `agent` / `vision` 等仍代表任务类型，与应用代码无关。网关统一输出上限 32000、总上下文上限 256000，客户端输出必须满足服务、授权及模型上限，超限直接拒绝。通过输出校验后再进行保守上下文检查；上下文估计不参与用量计量。

唯一候选、显式模型和已绑定工具续接不分类。分类器未授权 / 未配置 / 超时 / 无效结果时降级。无候选拒绝。执行至多两次尝试，只有明确可安全重试的拒绝或连接建立失败才重试；结果未知超时、开始输出后的错误不重试。

## 计量口径

核心 prompt / completion / total 数值必须有效且加和一致才能计入确认用量；可选子项不补零、不再次加和。保留白名单中的原始 usage 数值用于诊断，不保存任意供应商返回字段。流式最终 usage 即便在非空 choices 包中也采集，对外规范化为尾包。

请求受理时生成上海月份，后续 attempt 均继承根请求月份。报告直接聚合持久化数据，业务请求数单独去重；没有上游 attempt 的失败请求仍纳入业务失败率。按模型 / 阶段过滤时只计匹配 attempt 涉及的请求。CSV 空字段代表未提供的明细，unknown 列单独列出不完整用量。

## 本轮边界

无金额、余额、支付、客户登录、跨实例限流、图片存储、工具执行器、动态上游地址或用户自带 Key。支持本地运行及 Docker Compose 单机部署，后端保持单进程，不导入 MVP 重建之前的旧业务历史；本版自身的产品目录和限制变更通过 Alembic 保留现有身份与用量。平台管理员与公司是独立实体；终端用户入口由产品套件承担，当前 PP Code 使用公司应用密钥作为邀请码。

## 低消耗路由验收

管理员可通过 `/admin/v1/routing/preview` 选定应用密钥进行真实选路，复用正式认证、准入、能力过滤、分类和计量；请求必须使用 auto 且非流式。预览只计分类消耗，根请求记录 `purpose=routing_preview`、`execution_skipped=true`，实际执行模型为空。30 条评测因此不再触发 30 次业务生成。

# 可运行的服务端接入示例

[返回套件接入指南](../integration.md) · [API 字段与限制](../api-reference.md)

示例独立于 `pprouter` 内部代码，只需要 HTTP 地址和公司应用密钥。所有场景都在**显式运行命令后**调用真实网关，可能消耗供应商 token；不要把这些命令当成免费的测试套件。它们关闭隐式重试，也没有默认运行全部场景的入口。

## 准备

先让管理员为目标公司开通应用并签发密钥。示例 text / stream / image / tools 需要 `deepseek-flash` 权限；严格 JSON 示例使用 auto，需要 `kimi-k3.1-pro` 权限。应用 max_output_tokens 至少允许 256。

```sh
export PP_ROUTER_BASE_URL='https://150.158.155.100/v1'
# 通过私密环境配置 PP_ROUTER_API_KEY=该公司应用密钥。
# 本地网关可改为 http://127.0.0.1:4000/v1，并使用对应本地密钥。
```

完整地址说明见 [环境表](../environments.md)。不要使用供应商密钥、内部开户凭证、管理员密码或另一家公司密钥。

## Python

仓库开发环境已安装 `openai`。从仓库根目录选择**一个**命令运行：

```sh
uv run python docs/examples/client.py text
uv run python docs/examples/client.py stream
uv run python docs/examples/client.py image --image /你的本地路径/sample.png
uv run python docs/examples/client.py json
uv run python docs/examples/client.py tools
```

在其他套件中使用时，安装 `openai` 并复制 [client.py](client.py)，用自己的 Python 环境执行。示例在本仓库锁定的 OpenAI Python SDK 上验证；应用升级 SDK 后应验证协议与扩展字段仍兼容。

| 场景 | 行为与消耗范围 |
|---|---|
| text | 一次显式文本调用，最多 32 输出 token |
| stream | 一次显式流式调用，最多 128 输出 token；处理空 choices 和 usage |
| image | 一次显式图片调用，最多 256 输出 token；仅处理你指定的本地图片 |
| json | auto + 严格 JSON Schema，当前能力目录通常直接选择 Kimi；最多 256 输出 token |
| tools | 通常两次业务调用，各最多 256 输出 token；第二次 auto 使用已有工具绑定，不再分类 |

输出上限不是总 token 或金额上限；输入、图片、推理及可能的网关重试也会影响实际消耗。推理模型可能在很小的上限内无法完成回答，示例会保留结束原因，JSON 示例遇到截断直接失败，不自动追加调用。

工具示例只执行固定的本地演示订单查询，没有联网业务函数。它保留 assistant 的 tool_calls 和 reasoning_content，并验证函数名与参数。接入真实工具时，还必须检查当前用户对对应公司业务数据的访问权限。

流式示例检查结束原因并保留缺失用量提示。OpenAI SDK 隐藏了原始 `[DONE]`；需要严格检查原始尾标记的应用应使用自己的 SSE 消费层，不能仅以 SDK 迭代结束判定传输完整。

## Node.js

使用支持原生 fetch 的 Node.js；项目开发环境采用 Node.js 22.12+。无需安装 OpenAI Node SDK：

```sh
node docs/examples/chat.mjs
```

[chat.mjs](chat.mjs) 演示一次服务端 HTTP 调用、trace、错误判断和 usage 获取。不要直接搬进浏览器代码。

## 示例校验方式

文档维护时应使用临时数据库和测试替身验证字段、身份、用量及工具续接，不能为了修改文档而访问真实供应商。仓库常规检查仍使用 `make test`；这里的示例命令不属于默认 CI 的真实调用步骤。

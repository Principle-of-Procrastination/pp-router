# Production Hardening Requirements

> The access-key requirements below describe the 0.2.0 release and are superseded by `../public-access-refresh/requirements.md` from 0.3.0 onward.

## Scope

Harden the public pp-router deployment, remove Qwen, fix streaming and Chinese
classification correctness, persist usage history, and make deployment reproducible.

## Requirements

1. When the service starts, it shall reject missing security and provider secrets
   instead of using insecure defaults.
2. When an unauthenticated caller accesses models, chat, or history, the service
   shall return `401` without invoking an upstream model or reading history.
3. When a valid access key is submitted, the service shall issue a signed,
   expiring session token without returning or storing the access key in the Web app.
4. When request, rate, concurrency, output, or upstream-time limits are exceeded,
   the service shall fail with a bounded and non-sensitive error.
5. While an upstream stream is silent, the service shall emit heartbeats without
   cancelling the pending upstream read.
6. When the client disconnects or the stream ends abnormally, both server and Web
   client shall close the stream and shall not report a false successful completion.
7. When Chinese text contains overlapping or ambiguous keywords, the classifier
   shall use non-overlapping concepts and shall not treat common words such as
   `人类` as code.
8. When a short follow-up such as `继续` follows a complex user request, routing
   shall retain the prior task context.
9. When history is written or queried in production, it shall use the existing
   CloudBase NoSQL environment with bounded queries and server-only credentials.
10. The deployed model list shall not contain Qwen or require `QWEN_API_KEY`;
    `REASONING` shall route to `glm-5.1`.
11. The container build shall use one authoritative source tree, pinned
    dependencies, a non-root runtime user, and environment-injected secrets.
12. CI shall run backend tests and lint plus frontend type checking, tests, and build.

## Non-goals

- Creating a new paid PostgreSQL or MySQL instance.
- Rotating StepFun or BigModel credentials inside the vendors' account consoles.
- Rewriting Git history automatically to remove the old vendored LiteLLM objects.

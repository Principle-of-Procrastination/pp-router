# Implementation Plan

- [x] 1. Add validated runtime settings and remove Qwen
  - _Requirements: 1, 10_
- [x] 2. Add access-key sessions, rate limiting, and concurrency admission
  - _Requirements: 2, 3, 4_
- [x] 3. Replace JSONL history with CloudBase NoSQL plus SQLite fallback
  - _Requirements: 9_
- [x] 4. Fix SSE lifecycle, generic errors, request limits, and logging
  - _Requirements: 4, 5, 6_
- [x] 5. Fix Chinese matching and short follow-up routing
  - _Requirements: 7, 8_
- [x] 6. Add frontend session, cancellation, and truncated-stream handling
  - _Requirements: 2, 3, 6_
- [x] 7. Consolidate deployment, pin dependencies, remove vendored LiteLLM, and add CI
  - _Requirements: 11, 12_
- [x] 8. Run static, unit, browser, CloudBase review, and deployed smoke checks
  - _Requirements: 1-12_

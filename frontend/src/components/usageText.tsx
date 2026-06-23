import type { Usage } from "../api";

export function formatUsageTokens(usage: Usage): string {
  return `${usage.total_tokens} tok`;
}

export function formatUsageBreakdown(usage: Usage): string {
  return `${usage.prompt_tokens}/${usage.completion_tokens}`;
}

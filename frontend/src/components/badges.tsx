// 低饱和、暖调协调的档位色——避免亮绿/亮蓝那种通用感
const TIER_COLOR: Record<string, string> = {
  SIMPLE: "bg-[#181d15] text-[#a6bd98] ring-[#2d3a26]",
  MEDIUM: "bg-[#161c21] text-[#9fb5c6] ring-[#283742]",
  COMPLEX: "bg-[#211c15] text-[#cba883] ring-[#3a3020]",
  REASONING: "bg-[#1e1822] text-[#bb9dc9] ring-[#352a3d]",
};

export function TierBadge({ tier }: { tier: string | null }) {
  if (!tier) return null;
  const cls =
    TIER_COLOR[tier] ?? "bg-surface-2 text-fg-muted ring-line";
  return (
    <span
      className={`rounded-full px-2 py-0.5 font-mono text-[10px] tracking-wide ring-1 ring-inset ${cls}`}
    >
      {tier}
    </span>
  );
}

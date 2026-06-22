const TIER_COLOR: Record<string, string> = {
  SIMPLE: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30",
  MEDIUM: "bg-sky-500/15 text-sky-300 ring-sky-500/30",
  COMPLEX: "bg-amber-500/15 text-amber-300 ring-amber-500/30",
  REASONING: "bg-fuchsia-500/15 text-fuchsia-300 ring-fuchsia-500/30",
};

export function TierBadge({ tier }: { tier: string | null }) {
  if (!tier) return null;
  const cls =
    TIER_COLOR[tier] ?? "bg-slate-500/15 text-slate-300 ring-slate-500/30";
  return (
    <span
      className={`rounded px-1.5 py-0.5 text-[10px] font-medium ring-1 ring-inset ${cls}`}
    >
      {tier}
    </span>
  );
}

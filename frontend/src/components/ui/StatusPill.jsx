const TONES = {
  success: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  warning: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  danger: "bg-rose-500/15 text-rose-400 border-rose-500/30",
  neutral: "bg-slate-700/40 text-slate-400 border-slate-600/30",
};

export function StatusDot({ tone = "neutral" }) {
  const glow = {
    success: "bg-emerald-400 shadow-emerald-400/50",
    warning: "bg-amber-400 shadow-amber-400/50 animate-pulse",
    danger: "bg-rose-400 shadow-rose-400/50",
    neutral: "bg-slate-500 shadow-slate-500/50",
  };
  return (
    <span
      className={`inline-block w-2 h-2 rounded-full shadow-[0_0_8px] ${glow[tone] || glow.neutral}`}
    />
  );
}

export default function StatusPill({ tone = "neutral", dot = false, children, className = "" }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md border text-[11px] font-semibold ${
        TONES[tone] || TONES.neutral
      } ${className}`}
    >
      {dot && <StatusDot tone={tone} />}
      {children}
    </span>
  );
}

export function scoreTone(score) {
  if (score >= 80) return "success";
  if (score >= 50) return "warning";
  return "danger";
}

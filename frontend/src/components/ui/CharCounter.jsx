export default function CharCounter({ value, min, max }) {
  const len = (value || "").length;
  let tone = "text-slate-500";
  if (len === 0) tone = "text-slate-600";
  else if (len < min) tone = "text-amber-400";
  else if (len > max) tone = "text-rose-400";
  else tone = "text-emerald-400";
  return (
    <span className={`text-[10px] font-mono ${tone}`}>
      {len} / {max}
    </span>
  );
}

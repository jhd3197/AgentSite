export default function Toggle({ checked, onChange, size = "md", disabled = false }) {
  const dims =
    size === "sm"
      ? { track: "w-9 h-5", knob: "w-4 h-4", travel: "translate-x-4" }
      : { track: "w-10 h-6", knob: "w-5 h-5", travel: "translate-x-4" };
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={`relative ${dims.track} rounded-full transition-colors shrink-0 ${
        checked ? "bg-brand-500" : "bg-slate-700"
      } ${disabled ? "opacity-50 cursor-not-allowed" : ""}`}
    >
      <span
        className={`absolute top-0.5 left-0.5 ${dims.knob} bg-white rounded-full transition-transform ${
          checked ? dims.travel : "translate-x-0"
        }`}
      />
    </button>
  );
}

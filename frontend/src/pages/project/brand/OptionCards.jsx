export default function OptionCards({ options, value, onChange, renderThumb }) {
  return (
    <div className={options.length > 3 ? "grid grid-cols-2 sm:grid-cols-4 gap-3" : "grid grid-cols-3 gap-3"}>
      {options.map((opt) => {
        const active = value === opt.value;
        return (
          <button
            key={opt.value}
            onClick={() => onChange(opt.value)}
            className={`text-left p-3 rounded-lg border transition-colors ${
              active
                ? "border-brand-500 bg-brand-500/10 text-brand-400"
                : "border-slate-800 bg-slate-900 text-slate-400 hover:border-slate-600"
            }`}
          >
            {renderThumb && renderThumb(opt.value, active)}
            <span className="block text-sm font-medium mt-2">{opt.label}</span>
            <span className="block text-[10px] text-slate-500 mt-0.5">{opt.desc}</span>
          </button>
        );
      })}
    </div>
  );
}

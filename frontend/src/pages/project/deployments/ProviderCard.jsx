import { Check } from "@phosphor-icons/react";

export default function ProviderCard({ provider, connected, onSelect }) {
  return (
    <button
      onClick={() => onSelect(provider.id)}
      className={`group relative p-4 rounded-xl border text-left transition-all ${
        connected
          ? "border-brand-500/40 bg-brand-500/5"
          : "border-slate-800 bg-slate-900 hover:border-slate-700"
      }`}
    >
      <div
        className={`w-10 h-10 rounded-lg bg-gradient-to-br ${provider.color} flex items-center justify-center font-bold text-sm mb-3 border ${provider.accent}`}
      >
        {provider.name[0]}
      </div>
      <p className="text-sm font-semibold text-white">{provider.name}</p>
      <p className="text-[11px] text-slate-500 mt-0.5">{provider.desc}</p>
      {connected && (
        <span className="absolute top-3 right-3 w-5 h-5 rounded-full bg-brand-500 flex items-center justify-center">
          <Check size={12} weight="bold" className="text-white" />
        </span>
      )}
    </button>
  );
}

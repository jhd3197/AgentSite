import { useState } from "react";
import { Globe, Trash } from "@phosphor-icons/react";
import DeployStatusPill from "./DeployStatus";

export default function DomainRow({ domain, onRemove, onVerify }) {
  const [busy, setBusy] = useState(false);
  const handleVerify = async () => {
    setBusy(true);
    setTimeout(() => {
      onVerify(domain.host);
      setBusy(false);
    }, 1200);
  };
  return (
    <div className="flex items-center gap-3 px-4 py-3 border-b border-slate-800/60 last:border-0">
      <Globe size={16} className="text-slate-500 shrink-0" />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <p className="text-sm font-mono text-white truncate">{domain.host}</p>
          {domain.primary && (
            <span className="text-[10px] font-semibold text-brand-400 bg-brand-500/15 px-1.5 py-0.5 rounded">
              PRIMARY
            </span>
          )}
        </div>
        {!domain.verified && (
          <p className="text-[11px] text-amber-400 mt-0.5">
            Add CNAME → cname.agentsite.app
          </p>
        )}
      </div>
      {domain.verified ? (
        <DeployStatusPill status="ready" />
      ) : (
        <button
          onClick={handleVerify}
          disabled={busy}
          className="text-xs font-medium text-brand-400 hover:text-brand-300 disabled:opacity-50"
        >
          {busy ? "Verifying..." : "Verify"}
        </button>
      )}
      <button
        onClick={() => onRemove(domain.host)}
        className="text-slate-600 hover:text-rose-400 transition-colors p-1"
      >
        <Trash size={14} />
      </button>
    </div>
  );
}

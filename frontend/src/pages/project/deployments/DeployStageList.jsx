import { Check, CircleNotch } from "@phosphor-icons/react";
import { DEPLOY_STAGES } from "./constants";

export default function DeployStageList({ active, stages }) {
  return (
    <div className="space-y-2">
      {DEPLOY_STAGES.slice(0, -1).map((stage, i) => {
        const idx = DEPLOY_STAGES.findIndex((s) => s.id === active);
        const status = i < idx ? "done" : i === idx ? "running" : "pending";
        return (
          <div key={stage.id} className="flex items-center gap-3">
            <div
              className={`w-5 h-5 rounded-full flex items-center justify-center shrink-0 ${
                status === "done"
                  ? "bg-emerald-500/20 border border-emerald-500/40"
                  : status === "running"
                  ? "bg-amber-500/20 border border-amber-500/40"
                  : "bg-slate-800 border border-slate-700"
              }`}
            >
              {status === "done" && (
                <Check size={10} weight="bold" className="text-emerald-400" />
              )}
              {status === "running" && (
                <CircleNotch size={10} className="text-amber-400 animate-spin" />
              )}
            </div>
            <span
              className={`text-sm ${
                status === "done"
                  ? "text-slate-400"
                  : status === "running"
                  ? "text-white font-medium"
                  : "text-slate-600"
              }`}
            >
              {stage.label}
            </span>
            {stages[stage.id] && (
              <span className="ml-auto text-[11px] text-slate-600 font-mono">
                {stages[stage.id]}ms
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
}

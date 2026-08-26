import { useState } from "react";
import {
  Warning,
  Bug,
  CursorClick,
  LinkBreak,
  Repeat,
  PersonSimpleCircle,
  X,
  CaretUp,
  PaperPlaneRight,
} from "@phosphor-icons/react";

const TYPE_META = {
  js_error: { label: "JS error", icon: Bug, tone: "text-red-400 bg-red-500/10 border-red-500/30" },
  promise_rejection: { label: "Promise rejection", icon: Bug, tone: "text-red-400 bg-red-500/10 border-red-500/30" },
  console_error: { label: "console.error", icon: Bug, tone: "text-red-400 bg-red-500/10 border-red-500/30" },
  failed_request: { label: "Failed request", icon: LinkBreak, tone: "text-amber-400 bg-amber-500/10 border-amber-500/30" },
  failed_resource: { label: "Broken asset", icon: LinkBreak, tone: "text-amber-400 bg-amber-500/10 border-amber-500/30" },
  dead_click: { label: "Dead click", icon: CursorClick, tone: "text-purple-400 bg-purple-500/10 border-purple-500/30" },
  repeat_click: { label: "Repeated clicks", icon: Repeat, tone: "text-purple-400 bg-purple-500/10 border-purple-500/30" },
  a11y_violation: { label: "A11y", icon: UniversalAccess, tone: "text-cyan-400 bg-cyan-500/10 border-cyan-500/30" },
};

const ERROR_TYPES = ["js_error", "promise_rejection", "console_error"];
const REQUEST_TYPES = ["failed_request", "failed_resource"];
const FRICTION_TYPES = ["dead_click", "repeat_click"];

export function issueSummary(issues) {
  const counts = { errors: 0, requests: 0, friction: 0, a11y: 0 };
  for (const i of issues) {
    if (ERROR_TYPES.includes(i.type)) counts.errors++;
    else if (REQUEST_TYPES.includes(i.type)) counts.requests++;
    else if (FRICTION_TYPES.includes(i.type)) counts.friction++;
    else if (i.type === "a11y_violation") counts.a11y++;
  }
  return counts;
}

/**
 * Floating issues detector over the live preview. Appears once the injected
 * watcher reports friction (errors / dead clicks / broken requests) and lets
 * the user hand everything to the developer agent as structured feedback.
 */
export default function WatchIssuesPanel({ issues, onSend, onDismiss, disabled }) {
  const [open, setOpen] = useState(false);
  if (!issues.length) return null;

  const summary = issueSummary(issues);
  const parts = [
    summary.errors && `${summary.errors} error${summary.errors > 1 ? "s" : ""}`,
    summary.requests && `${summary.requests} broken request${summary.requests > 1 ? "s" : ""}`,
    summary.friction && `${summary.friction} dead click${summary.friction > 1 ? "s" : ""}`,
    summary.a11y && `${summary.a11y} a11y`,
  ].filter(Boolean);

  return (
    <div className="absolute bottom-4 right-4 z-30 flex flex-col items-end gap-2 max-w-md">
      {open && (
        <div className="w-full bg-slate-950/95 backdrop-blur border border-slate-700 rounded-xl shadow-2xl overflow-hidden">
          <div className="flex items-center justify-between px-3 py-2 border-b border-slate-800">
            <span className="text-xs font-semibold text-slate-200 flex items-center gap-1.5">
              <Warning size={13} weight="fill" className="text-amber-400" />
              Detected while you browsed
            </span>
            <button onClick={() => setOpen(false)} className="text-slate-500 hover:text-white">
              <X size={13} />
            </button>
          </div>
          <div className="max-h-64 overflow-y-auto divide-y divide-slate-800/70">
            {issues.map((issue, idx) => {
              const meta = TYPE_META[issue.type] || TYPE_META.js_error;
              const Icon = meta.icon;
              return (
                <div key={idx} className="px-3 py-2 flex items-start gap-2.5 hover:bg-slate-900/60">
                  <span className={`mt-0.5 shrink-0 inline-flex items-center justify-center w-5 h-5 rounded border ${meta.tone}`}>
                    <Icon size={11} weight="fill" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="text-xs text-slate-300 leading-snug break-words">{issue.message}</p>
                    {(issue.selector || issue.type === "dead_click") && (
                      <p className="mt-0.5 text-[10px] font-mono text-slate-500 truncate">
                        {meta.label}
                        {issue.selector ? ` · ${issue.selector}` : ""}
                        {issue.href ? ` · href=${issue.href}` : ""}
                      </p>
                    )}
                  </div>
                  {issue.count > 1 && (
                    <span className="shrink-0 text-[10px] font-mono text-slate-400 bg-slate-800 rounded px-1.5 py-0.5">
                      x{issue.count}
                    </span>
                  )}
                </div>
              );
            })}
          </div>
          <div className="flex items-center justify-between px-3 py-2 border-t border-slate-800">
            <button
              onClick={onDismiss}
              className="text-xs text-slate-500 hover:text-slate-300 transition-colors"
            >
              Dismiss
            </button>
            <button
              onClick={onSend}
              disabled={disabled}
              title={disabled ? "Wait for the current build to finish" : "Start a fix run with these observations"}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-brand-500 hover:bg-brand-400 disabled:opacity-50 disabled:cursor-not-allowed text-white text-xs font-semibold transition-colors"
            >
              Send to developer
              <PaperPlaneRight size={12} weight="fill" />
            </button>
          </div>
        </div>
      )}

      <button
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-2 pl-3 pr-2.5 py-2 rounded-full bg-slate-950/95 backdrop-blur border border-amber-500/40 shadow-xl hover:border-amber-400 transition-colors"
      >
        <span className="relative flex h-2 w-2">
          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-amber-400 opacity-60" />
          <span className="relative inline-flex rounded-full h-2 w-2 bg-amber-400" />
        </span>
        <span className="text-xs font-medium text-slate-200">
          {issues.length} issue{issues.length > 1 ? "s" : ""} · {parts.join(", ")}
        </span>
        <CaretUp
          size={12}
          className={`text-slate-500 transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>
    </div>
  );
}

import {
  Rocket,
  Globe,
  Check,
  CircleNotch,
  ArrowSquareOut,
  Copy,
  GitBranch,
  Lock,
} from "@phosphor-icons/react";
import DeployStatusPill from "./DeployStatus";
import DeployStageList from "./DeployStageList";
import { fmtRelative } from "../../../lib/format";

export default function DeployHero({ project, d, copied, onCopy }) {
  const { deploying, stage, stageTimes, lastReady, primaryDomain, cfg, history, domains, runDeploy } = d;
  return (
    <div className="relative overflow-hidden rounded-2xl border border-slate-800 bg-gradient-to-br from-slate-900 via-slate-900 to-brand-950/40 p-8">
      <div className="absolute -top-20 -right-20 w-64 h-64 bg-brand-500/10 rounded-full blur-3xl pointer-events-none" />
      <div className="relative flex items-start justify-between gap-8">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-3 mb-2">
            <DeployStatusPill status={lastReady ? "ready" : "queued"} />
            <span className="text-xs text-slate-500">
              {lastReady
                ? `Deployed ${fmtRelative(lastReady.finished_at)}`
                : "Never deployed"}
            </span>
          </div>
          <h1 className="text-3xl font-bold text-white mb-3">
            {project?.name || "Project"}
          </h1>
          <button
            onClick={onCopy}
            className="group inline-flex items-center gap-2 text-sm text-slate-300 hover:text-white transition-colors"
          >
            <Lock size={12} className="text-emerald-400" />
            <code className="font-mono">https://{primaryDomain}</code>
            {copied ? (
              <Check size={14} className="text-emerald-400" weight="bold" />
            ) : (
              <Copy size={14} className="text-slate-500 group-hover:text-white" />
            )}
          </button>
          <div className="flex flex-wrap items-center gap-x-6 gap-y-2 mt-4 text-xs text-slate-400">
            <span className="flex items-center gap-1.5">
              <GitBranch size={12} />
              {cfg.branch}
            </span>
            <span className="flex items-center gap-1.5">
              <Rocket size={12} />
              {history.length} deploy{history.length === 1 ? "" : "s"}
            </span>
            <span className="flex items-center gap-1.5">
              <Globe size={12} />
              {domains.filter((x) => x.verified).length} custom domain
              {domains.filter((x) => x.verified).length === 1 ? "" : "s"}
            </span>
          </div>
        </div>

        <div className="shrink-0 flex flex-col items-end gap-3">
          <button
            onClick={() => runDeploy("production")}
            disabled={deploying}
            className="inline-flex items-center gap-2 bg-white text-slate-950 px-5 py-2.5 rounded-lg text-sm font-semibold hover:bg-slate-100 transition-colors shadow-lg shadow-white/10 disabled:opacity-60 disabled:cursor-not-allowed"
          >
            {deploying ? (
              <>
                <CircleNotch size={16} className="animate-spin" />
                Deploying...
              </>
            ) : (
              <>
                <Rocket size={16} weight="fill" />
                Deploy to production
              </>
            )}
          </button>
          <a
            href={`https://${primaryDomain}`}
            target="_blank"
            rel="noreferrer"
            className="text-xs text-slate-500 hover:text-slate-300 inline-flex items-center gap-1"
          >
            Visit site <ArrowSquareOut size={11} />
          </a>
        </div>
      </div>

      {deploying && (
        <div className="relative mt-6 p-4 bg-slate-950/60 border border-slate-800 rounded-lg">
          <DeployStageList active={stage} stages={stageTimes} />
        </div>
      )}
    </div>
  );
}

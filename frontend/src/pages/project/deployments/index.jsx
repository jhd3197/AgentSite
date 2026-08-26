import { useParams } from "react-router-dom";
import { Plus, Clock, Check } from "@phosphor-icons/react";
import useProject from "../../../hooks/useProject";
import useFlash from "../../../hooks/useFlash";
import PageHeader from "../../../components/ui/PageHeader";
import PageLoading from "../../../components/ui/PageLoading";
import Panel from "../../../components/ui/Panel";
import SectionHeader from "../../../components/ui/SectionHeader";
import TextField from "../../../components/ui/TextField";
import Toggle from "../../../components/ui/Toggle";
import Button from "../../../components/ui/Button";
import { fmtRelative } from "../../../lib/format";
import useDeployment from "./useDeployment";
import { PROVIDERS, ENVS } from "./constants";
import DeployStatusPill from "./DeployStatus";
import ProviderCard from "./ProviderCard";
import DomainRow from "./DomainRow";
import EnvVarRow from "./EnvVarRow";
import DeployHero from "./DeployHero";

export default function DeploymentsPage() {
  const { projectId } = useParams();
  const { project, pages, loading } = useProject(projectId);
  const d = useDeployment({ projectId, pageCount: pages.length });
  const [copied, flashCopied] = useFlash(1500);

  if (loading) return <PageLoading />;

  const copyUrl = () => {
    navigator.clipboard?.writeText(`https://${d.primaryDomain}`);
    flashCopied();
  };

  return (
    <div className="flex-1 overflow-y-auto">
      <PageHeader
        items={[
          { label: "Projects" },
          { label: project?.name || "...", to: `/project/${projectId}` },
          { label: "Deployments" },
        ]}
      />

      <div className="p-8 pb-16">
        <div className="max-w-6xl mx-auto space-y-8">
          <DeployHero project={project} d={d} copied={copied} onCopy={copyUrl} />

          <section>
            <SectionHeader title="Environments" variant="label" />
            <div className="grid grid-cols-3 gap-4">
              {ENVS.map(({ id, label, icon: Icon }) => {
                const last = d.history.find(
                  (h) => h.env === id && h.status === "ready"
                );
                return (
                  <Panel key={id} className="p-5 flex flex-col">
                    <div className="flex items-center justify-between mb-3">
                      <div className="flex items-center gap-2">
                        <Icon size={16} className="text-brand-400" />
                        <span className="text-sm font-semibold text-white">{label}</span>
                      </div>
                      <DeployStatusPill status={last ? "ready" : "queued"} />
                    </div>
                    <p className="text-xs text-slate-500 mb-4">
                      {last
                        ? `Updated ${fmtRelative(last.finished_at)}`
                        : "No deployments yet"}
                    </p>
                    <Button
                      variant="secondary"
                      size="sm"
                      disabled={d.deploying}
                      onClick={() => d.runDeploy(id)}
                      className="w-full mt-auto"
                    >
                      Deploy {label.toLowerCase()}
                    </Button>
                  </Panel>
                );
              })}
            </div>
          </section>

          <div className="grid grid-cols-[1fr_360px] gap-6">
            <section>
              <SectionHeader title="Hosting provider" variant="label" />
              <div className="grid grid-cols-4 gap-3">
                {PROVIDERS.map((p) => (
                  <ProviderCard
                    key={p.id}
                    provider={p}
                    connected={d.cfg.provider === p.id}
                    onSelect={(id) =>
                      d.setCfg({
                        ...d.cfg,
                        provider: d.cfg.provider === id ? null : id,
                      })
                    }
                  />
                ))}
              </div>
              {d.cfg.provider && (
                <div className="mt-3 text-xs text-slate-500 flex items-center gap-2">
                  <Check size={12} className="text-emerald-400" weight="bold" />
                  Connected to{" "}
                  <span className="text-slate-300 font-medium">
                    {PROVIDERS.find((p) => p.id === d.cfg.provider)?.name}
                  </span>
                  . The next deploy will push there.
                </div>
              )}
            </section>

            <section>
              <SectionHeader title="Build settings" variant="label" />
              <Panel className="p-4 space-y-3">
                <TextField
                  label="Production branch"
                  mono
                  size="sm"
                  value={d.cfg.branch}
                  onChange={(v) => d.setCfg({ ...d.cfg, branch: v })}
                />
                <TextField
                  label="Build command"
                  mono
                  size="sm"
                  value={d.cfg.build_command}
                  onChange={(v) => d.setCfg({ ...d.cfg, build_command: v })}
                />
                <TextField
                  label="Output directory"
                  mono
                  size="sm"
                  value={d.cfg.output_dir}
                  onChange={(v) => d.setCfg({ ...d.cfg, output_dir: v })}
                />
                <label className="flex items-center justify-between gap-3 pt-2 border-t border-slate-800 cursor-pointer">
                  <div>
                    <p className="text-sm text-white">Auto-deploy on changes</p>
                    <p className="text-[11px] text-slate-500">
                      Trigger a deploy whenever a page is generated.
                    </p>
                  </div>
                  <Toggle
                    size="sm"
                    checked={d.cfg.auto_deploy}
                    onChange={(v) => d.setCfg({ ...d.cfg, auto_deploy: v })}
                  />
                </label>
              </Panel>
            </section>
          </div>

          <section>
            <SectionHeader title="Custom domains" variant="label" />
            <Panel className="overflow-hidden">
              <div className="flex items-center gap-2 p-4 border-b border-slate-800">
                <input
                  value={d.newDomain}
                  onChange={(e) => d.setNewDomain(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && d.addDomain()}
                  placeholder="www.example.com"
                  className="flex-1 bg-slate-950 border border-slate-800 text-white text-sm font-mono rounded-md py-2 px-3 focus:border-brand-500 focus:outline-none"
                />
                <Button
                  variant="brand"
                  size="sm"
                  disabled={!d.newDomain.trim()}
                  onClick={d.addDomain}
                >
                  <Plus size={14} weight="bold" />
                  Add domain
                </Button>
              </div>
              {d.domains.length === 0 ? (
                <div className="p-8 text-center text-sm text-slate-500">
                  No custom domains yet. Your site is live at{" "}
                  <code className="font-mono text-slate-400">{d.primaryDomain}</code>
                </div>
              ) : (
                <div>
                  {d.domains.map((dom) => (
                    <DomainRow
                      key={dom.host}
                      domain={dom}
                      onRemove={d.removeDomain}
                      onVerify={d.verifyDomain}
                    />
                  ))}
                </div>
              )}
            </Panel>
            {d.domains.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-2">
                {d.domains
                  .filter((dom) => dom.verified && !dom.primary)
                  .map((dom) => (
                    <button
                      key={dom.host}
                      onClick={() => d.setPrimary(dom.host)}
                      className="text-[11px] text-slate-500 hover:text-brand-400"
                    >
                      Make {dom.host} primary
                    </button>
                  ))}
              </div>
            )}
          </section>

          <section>
            <div className="flex items-center justify-between mb-4">
              <SectionHeader title="Environment variables" variant="label" as="h2" className="mb-0" />
              <button
                onClick={d.addEnvVar}
                className="text-xs font-medium text-brand-400 hover:text-brand-300 inline-flex items-center gap-1"
              >
                <Plus size={12} weight="bold" /> Add variable
              </button>
            </div>
            <Panel className="p-4">
              {d.envVars.length === 0 ? (
                <div className="text-center py-6 text-sm text-slate-500">
                  No env vars yet. Add API keys and secrets here — they'll be injected at
                  build time.
                </div>
              ) : (
                <div className="space-y-1">
                  <div className="grid grid-cols-[1fr_1fr_auto_auto] gap-2 text-[10px] font-semibold text-slate-500 uppercase tracking-wider px-1 mb-1">
                    <span>Key</span>
                    <span>Value</span>
                    <span />
                    <span />
                  </div>
                  {d.envVars.map((env, idx) => (
                    <EnvVarRow
                      key={idx}
                      env={env}
                      onUpdate={(updated) => d.updateEnvVar(idx, updated)}
                      onRemove={() => {
                        const next = [...d.envVars];
                        next.splice(idx, 1);
                        d.setEnvVars(next);
                      }}
                    />
                  ))}
                </div>
              )}
            </Panel>
          </section>

          <section>
            <SectionHeader title="Deployment history" variant="label" />
            <Panel className="overflow-hidden">
              {d.history.length === 0 ? (
                <div className="p-12 text-center">
                  <Clock size={28} className="text-slate-700 mx-auto mb-3" />
                  <p className="text-sm text-slate-500">
                    No deployments yet — hit{" "}
                    <span className="text-slate-300 font-medium">
                      Deploy to production
                    </span>{" "}
                    to ship your first version.
                  </p>
                </div>
              ) : (
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-[10px] uppercase tracking-wider text-slate-500 border-b border-slate-800">
                      <th className="text-left px-5 py-2.5 font-semibold">Status</th>
                      <th className="text-left px-5 py-2.5 font-semibold">Commit</th>
                      <th className="text-left px-5 py-2.5 font-semibold">Env</th>
                      <th className="text-left px-5 py-2.5 font-semibold">Branch</th>
                      <th className="text-left px-5 py-2.5 font-semibold">Duration</th>
                      <th className="text-left px-5 py-2.5 font-semibold">When</th>
                      <th className="text-right px-5 py-2.5 font-semibold">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {d.history.map((dep) => (
                      <tr
                        key={dep.id}
                        className="border-b border-slate-800/60 last:border-0 hover:bg-slate-800/30"
                      >
                        <td className="px-5 py-3">
                          <DeployStatusPill status={dep.status} />
                        </td>
                        <td className="px-5 py-3">
                          <p className="text-white text-xs font-mono">{dep.commit}</p>
                          <p className="text-[11px] text-slate-500 truncate max-w-[260px]">
                            {dep.message}
                          </p>
                        </td>
                        <td className="px-5 py-3 text-slate-400 text-xs capitalize">
                          {dep.env}
                        </td>
                        <td className="px-5 py-3 text-slate-400 text-xs font-mono">
                          {dep.branch}
                        </td>
                        <td className="px-5 py-3 text-slate-400 text-xs font-mono">
                          {dep.duration_ms ? `${(dep.duration_ms / 1000).toFixed(1)}s` : "—"}
                        </td>
                        <td className="px-5 py-3 text-slate-400 text-xs">
                          {fmtRelative(dep.started_at)}
                        </td>
                        <td className="px-5 py-3 text-right">
                          {dep.status === "ready" && (
                            <button
                              onClick={() => d.runDeploy(dep.env)}
                              disabled={d.deploying}
                              className="text-xs text-slate-500 hover:text-brand-400 disabled:opacity-50"
                            >
                              Redeploy
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </Panel>
          </section>
        </div>
      </div>
    </div>
  );
}

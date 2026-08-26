import {
  ChartLineUp,
  Check,
  Warning,
  X,
} from "@phosphor-icons/react";
import Panel from "../../../components/ui/Panel";
import ScorePill from "./ScorePill";
import { scoreAllPages } from "./seoScore";

function StatCard({ label, value, tone = "text-white" }) {
  return (
    <Panel className="p-5">
      <p className="text-xs text-slate-500 mb-2">{label}</p>
      <p className={`text-3xl font-bold ${tone}`}>{value}</p>
    </Panel>
  );
}

export default function HealthTab({ pages, pageSeo, site }) {
  const rows = scoreAllPages(pages, pageSeo);

  const avg = rows.length
    ? Math.round(rows.reduce((sum, r) => sum + r.score, 0) / rows.length)
    : 0;

  const allChecks = rows.flatMap((r) => r.checks);
  const passing = allChecks.filter((c) => c.ok).length;
  const failing = allChecks.length - passing;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-4 gap-4">
        <StatCard label="Site SEO score" value={`${avg}`} />
        <StatCard label="Pages indexed" value={pages.length} />
        <StatCard label="Checks passing" value={passing} tone="text-emerald-400" />
        <StatCard label="Checks failing" value={failing} tone="text-rose-400" />
      </div>

      <Panel className="overflow-hidden">
        <div className="px-5 py-3 border-b border-slate-800 flex items-center gap-2">
          <ChartLineUp size={16} className="text-slate-500" />
          <h3 className="text-sm font-semibold text-white">Per-page breakdown</h3>
        </div>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-xs text-slate-500 border-b border-slate-800">
              <th className="text-left px-5 py-2.5 font-medium">Page</th>
              <th className="text-left px-5 py-2.5 font-medium">Title</th>
              <th className="text-left px-5 py-2.5 font-medium">Description</th>
              <th className="text-left px-5 py-2.5 font-medium">OG image</th>
              <th className="text-left px-5 py-2.5 font-medium">Canonical</th>
              <th className="text-right px-5 py-2.5 font-medium">Score</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(({ page, score, checks }) => (
              <tr key={page.slug} className="border-b border-slate-800/60 last:border-0">
                <td className="px-5 py-3">
                  <p className="text-white font-medium">{page.title || page.slug}</p>
                  <p className="text-[10px] text-slate-500 font-mono">/{page.slug}</p>
                </td>
                {checks.map((c) => (
                  <td key={c.label} className="px-5 py-3">
                    {c.ok ? (
                      <Check className="text-emerald-400" size={16} weight="bold" />
                    ) : c.warn ? (
                      <Warning className="text-amber-400" size={16} weight="fill" />
                    ) : (
                      <X className="text-rose-400" size={16} weight="bold" />
                    )}
                  </td>
                ))}
                <td className="px-5 py-3 text-right">
                  <ScorePill score={score} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>

      {!site.canonical_base && (
        <div className="bg-amber-500/10 border border-amber-500/30 rounded-xl p-4 flex gap-3">
          <Warning className="text-amber-400 shrink-0 mt-0.5" size={18} weight="fill" />
          <div>
            <p className="text-sm font-medium text-amber-300">No canonical base URL set</p>
            <p className="text-xs text-amber-200/80 mt-0.5">
              Set it under the Site tab to enable proper canonical tags, OG URLs, and a
              valid sitemap.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

import { useState, useMemo, useEffect } from "react";
import { useParams } from "react-router-dom";
import { Globe, FileText, ChartLineUp, Check } from "@phosphor-icons/react";
import useProject from "../../../hooks/useProject";
import useLocalStorage from "../../../hooks/useLocalStorage";
import useFlash from "../../../hooks/useFlash";
import PageHeader from "../../../components/ui/PageHeader";
import PageLoading from "../../../components/ui/PageLoading";
import TabButton from "../../../components/ui/TabButton";
import ScorePill from "./ScorePill";
import SiteTab from "./SiteTab";
import PagesTab from "./PagesTab";
import HealthTab from "./HealthTab";
import { scoreAllPages } from "./seoScore";

const DEFAULT_SITE = {
  site_title: "",
  site_description: "",
  default_og_image: "",
  canonical_base: "",
  robots_txt: "User-agent: *\nAllow: /\n\nSitemap: {{canonical_base}}/sitemap.xml",
  sitemap_enabled: true,
  google_verification: "",
  bing_verification: "",
  twitter_handle: "",
  default_robots: "index,follow",
};

export default function SeoPage() {
  const { projectId } = useParams();
  const { project, pages, loading } = useProject(projectId);

  const [site, setSite] = useLocalStorage(
    `agentsite:seo:site:${projectId}`,
    DEFAULT_SITE
  );
  const [pageSeo, setPageSeoState] = useLocalStorage(
    `agentsite:seo:pages:${projectId}`,
    {}
  );
  const [activeTab, setActiveTab] = useState("pages");
  const [savedFlash, flashSaved] = useFlash(1500);

  const setPageSeo = (next) => {
    setPageSeoState(next);
    flashSaved();
  };

  useEffect(() => {
    if (project && !site.site_title) {
      setSite((s) => ({ ...s, site_title: project.name }));
    }
  }, [project?.id]);

  const avgScore = useMemo(() => {
    if (!pages.length) return 0;
    const rows = scoreAllPages(pages, pageSeo);
    return Math.round(rows.reduce((sum, r) => sum + r.score, 0) / rows.length);
  }, [pages, pageSeo]);

  if (loading) return <PageLoading />;

  return (
    <div className="flex-1 overflow-y-auto">
      <PageHeader
        items={[
          { label: "Projects" },
          { label: project?.name || "...", to: `/project/${projectId}` },
          { label: "SEO" },
        ]}
      />

      <div className="p-8 pb-16">
        <div className="max-w-7xl mx-auto">
          <div className="flex items-start justify-between mb-6 gap-6">
            <div>
              <h1 className="text-2xl font-bold text-white flex items-center gap-3">
                Search Engine Optimization
                <ScorePill score={avgScore} />
              </h1>
              <p className="text-sm text-slate-500 mt-1">
                Configure meta tags, sharing previews, and indexing rules for every
                page. Changes are saved locally and applied on the next deploy.
              </p>
            </div>
            <div
              className={`text-xs px-3 py-1.5 rounded-full transition-opacity ${
                savedFlash
                  ? "opacity-100 bg-emerald-500/15 text-emerald-400 border border-emerald-500/30"
                  : "opacity-0"
              }`}
            >
              <Check size={12} weight="bold" className="inline mr-1" />
              Saved
            </div>
          </div>

          <div className="border-b border-slate-800 mb-6 flex items-center gap-1">
            <TabButton
              active={activeTab === "pages"}
              onClick={() => setActiveTab("pages")}
              icon={FileText}
              count={pages.length}
            >
              Pages
            </TabButton>
            <TabButton
              active={activeTab === "site"}
              onClick={() => setActiveTab("site")}
              icon={Globe}
            >
              Site defaults
            </TabButton>
            <TabButton
              active={activeTab === "health"}
              onClick={() => setActiveTab("health")}
              icon={ChartLineUp}
            >
              Health
            </TabButton>
          </div>

          {activeTab === "pages" && (
            <PagesTab
              projectId={projectId}
              pages={pages}
              pageSeo={pageSeo}
              setPageSeo={setPageSeo}
              site={site}
            />
          )}
          {activeTab === "site" && <SiteTab site={site} setSite={setSite} />}
          {activeTab === "health" && (
            <HealthTab pages={pages} pageSeo={pageSeo} site={site} />
          )}
        </div>
      </div>
    </div>
  );
}

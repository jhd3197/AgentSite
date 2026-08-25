import {
  Check,
  Warning,
  X,
  MagnifyingGlass,
  ShareNetwork,
  Link as LinkIcon,
  FacebookLogo,
  TwitterLogo,
  FileText,
} from "@phosphor-icons/react";
import { useState } from "react";
import TextField from "../../../components/ui/TextField";
import TextAreaField from "../../../components/ui/TextAreaField";
import CharCounter from "../../../components/ui/CharCounter";
import Panel from "../../../components/ui/Panel";
import SerpPreview from "./SerpPreview";
import SocialPreview from "./SocialPreview";
import ScorePill from "./ScorePill";
import {
  TITLE_MIN,
  TITLE_MAX,
  DESC_MIN,
  DESC_MAX,
  getPageSeo,
  scorePageSeo,
} from "./seoScore";

function AuditRow({ check }) {
  return (
    <div className="flex items-center justify-between gap-3 py-1.5 text-sm">
      <div className="flex items-center gap-2 text-slate-300">
        {check.ok ? (
          <Check className="text-emerald-400" size={14} weight="bold" />
        ) : check.warn ? (
          <Warning className="text-amber-400" size={14} weight="fill" />
        ) : (
          <X className="text-rose-400" size={14} weight="bold" />
        )}
        {check.label}
      </div>
      <span className="text-xs text-slate-500">{check.msg}</span>
    </div>
  );
}

export default function PagesTab({ projectId, pages, pageSeo, setPageSeo, site }) {
  const [selectedSlug, setSelectedSlug] = useState(pages[0]?.slug || null);
  const [socialView, setSocialView] = useState("facebook");

  if (pages.length === 0) {
    return (
      <Panel className="p-10 text-center">
        <FileText className="text-slate-600 mx-auto mb-3" size={32} />
        <p className="text-sm text-slate-500">
          No pages yet — create a page on the project Overview to configure SEO.
        </p>
      </Panel>
    );
  }

  const page = pages.find((p) => p.slug === selectedSlug) || pages[0];
  const seo = getPageSeo(pageSeo, page.slug);
  const update = (k, v) =>
    setPageSeo({ ...pageSeo, [page.slug]: { ...seo, [k]: v } });

  const { score, checks } = scorePageSeo(seo, page);

  return (
    <div className="grid grid-cols-[220px_1fr_360px] gap-6">
      <div className="space-y-1">
        <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider px-2 mb-2">
          Pages ({pages.length})
        </p>
        {pages.map((p) => (
          <button
            key={p.slug}
            onClick={() => setSelectedSlug(p.slug)}
            className={`w-full flex items-center justify-between gap-2 px-3 py-2 rounded-lg text-left text-sm transition-colors ${
              p.slug === page.slug
                ? "bg-brand-500/10 text-white border border-brand-500/30"
                : "text-slate-400 hover:bg-slate-900 border border-transparent"
            }`}
          >
            <div className="min-w-0 flex-1">
              <p className="font-medium truncate">{p.title || p.slug}</p>
              <p className="text-[10px] text-slate-500 font-mono truncate">/{p.slug}</p>
            </div>
            <ScorePill score={scorePageSeo(getPageSeo(pageSeo, p.slug), p).score} />
          </button>
        ))}
      </div>

      <div className="space-y-5 min-w-0">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <h3 className="text-base font-semibold text-white truncate">
              {page.title || page.slug}
            </h3>
            <ScorePill score={score} />
          </div>
          <p className="text-xs text-slate-500 font-mono">/{page.slug}</p>
        </div>

        <TextField
          label="Title tag"
          hint={`Aim for ${TITLE_MIN}–${TITLE_MAX} characters.`}
          counter={<CharCounter value={seo.title} min={TITLE_MIN} max={TITLE_MAX} />}
          value={seo.title}
          onChange={(v) => update("title", v)}
          placeholder={page.title || "Page title"}
        />

        <TextAreaField
          label="Meta description"
          counter={<CharCounter value={seo.description} min={DESC_MIN} max={DESC_MAX} />}
          value={seo.description}
          onChange={(v) => update("description", v)}
          placeholder="What this page is about, in one or two sentences."
        />

        <TextField
          label="Keywords"
          hint="Optional. Comma-separated. Most engines ignore this."
          value={seo.keywords}
          onChange={(v) => update("keywords", v)}
          placeholder="charter, yacht, mediterranean"
        />

        <div className="grid grid-cols-2 gap-4">
          <TextField
            label="Canonical URL"
            mono
            value={seo.canonical}
            onChange={(v) => update("canonical", v)}
            placeholder={`${site.canonical_base || "https://yoursite.com"}/${
              page.slug === "home" ? "" : page.slug
            }`}
          />
          <TextField
            label="Robots"
            mono
            value={seo.robots}
            onChange={(v) => update("robots", v)}
            placeholder="index,follow"
          />
        </div>

        <div className="pt-4 border-t border-slate-800">
          <p className="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-3">
            Social sharing
          </p>
          <div className="space-y-4">
            <TextField
              label="OG title"
              counter={<CharCounter value={seo.og_title} min={10} max={70} />}
              value={seo.og_title}
              onChange={(v) => update("og_title", v)}
              placeholder="Falls back to title tag"
            />
            <TextAreaField
              label="OG description"
              counter={<CharCounter value={seo.og_description} min={30} max={200} />}
              value={seo.og_description}
              onChange={(v) => update("og_description", v)}
              placeholder="Falls back to meta description"
            />
            <TextField
              label="OG image"
              hint="Asset path (relative to project assets). Recommended 1200×630."
              mono
              value={seo.og_image}
              onChange={(v) => update("og_image", v)}
              placeholder={site.default_og_image || "share-image.png"}
            />
          </div>
        </div>

        <div className="pt-4 border-t border-slate-800">
          <p className="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-3">
            Audit
          </p>
          <div className="space-y-2">
            {checks.map((c) => (
              <AuditRow key={c.label} check={c} />
            ))}
          </div>
        </div>
      </div>

      <div className="space-y-5">
        <div>
          <div className="flex items-center gap-2 mb-3">
            <MagnifyingGlass size={14} className="text-slate-500" />
            <p className="text-xs font-semibold text-slate-400 uppercase tracking-wide">
              Search preview
            </p>
          </div>
          <SerpPreview canonicalBase={site.canonical_base} page={page} seo={seo} />
        </div>

        <div>
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <ShareNetwork size={14} className="text-slate-500" />
              <p className="text-xs font-semibold text-slate-400 uppercase tracking-wide">
                Social preview
              </p>
            </div>
            <div className="flex bg-slate-900 border border-slate-800 rounded-md p-0.5">
              <button
                onClick={() => setSocialView("facebook")}
                className={`p-1 rounded ${
                  socialView === "facebook" ? "bg-slate-800 text-white" : "text-slate-500"
                }`}
              >
                <FacebookLogo size={14} weight="fill" />
              </button>
              <button
                onClick={() => setSocialView("twitter")}
                className={`p-1 rounded ${
                  socialView === "twitter" ? "bg-slate-800 text-white" : "text-slate-500"
                }`}
              >
                <TwitterLogo size={14} weight="fill" />
              </button>
            </div>
          </div>
          <SocialPreview
            projectId={projectId}
            page={page}
            seo={seo}
            defaultOg={site.default_og_image}
          />
        </div>

        <Panel rounded="lg" className="p-3">
          <div className="flex items-center gap-2 mb-2">
            <LinkIcon size={12} className="text-slate-500" />
            <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-wide">
              Rendered URL
            </p>
          </div>
          <code className="text-[11px] font-mono text-emerald-300 break-all">
            {(site.canonical_base || "https://yoursite.com") +
              (page.slug === "home" ? "" : "/" + page.slug)}
          </code>
        </Panel>
      </div>
    </div>
  );
}

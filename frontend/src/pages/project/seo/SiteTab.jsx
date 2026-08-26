import TextField from "../../../components/ui/TextField";
import TextAreaField from "../../../components/ui/TextAreaField";
import CharCounter from "../../../components/ui/CharCounter";
import Toggle from "../../../components/ui/Toggle";
import SectionHeader from "../../../components/ui/SectionHeader";
import { DESC_MIN, DESC_MAX } from "./seoScore";

export default function SiteTab({ site, setSite }) {
  const update = (k, v) => setSite({ ...site, [k]: v });
  return (
    <div className="space-y-8 max-w-2xl">
      <section>
        <SectionHeader
          title="Site identity"
          description="Defaults applied to every page that doesn't override them."
        />
        <div className="space-y-4">
          <TextField
            label="Default site title"
            hint="Used as fallback and appended to page titles (e.g. 'About — Site')."
            counter={<CharCounter value={site.site_title} min={5} max={60} />}
            value={site.site_title}
            onChange={(v) => update("site_title", v)}
            placeholder="YachtMind — luxury chartering platform"
          />
          <TextAreaField
            label="Default meta description"
            counter={
              <CharCounter value={site.site_description} min={DESC_MIN} max={DESC_MAX} />
            }
            value={site.site_description}
            onChange={(v) => update("site_description", v)}
            placeholder="Describe your site in one or two sentences."
          />
          <TextField
            label="Canonical base URL"
            hint="The production URL. Used to build canonical tags and sitemap entries."
            mono
            value={site.canonical_base}
            onChange={(v) => update("canonical_base", v)}
            placeholder="https://yachtmind.com"
          />
          <TextField
            label="Default OG image path"
            hint="Asset path served from /preview/{project}/assets/. Used when a page has no OG image of its own."
            mono
            value={site.default_og_image}
            onChange={(v) => update("default_og_image", v)}
            placeholder="og-default.png"
          />
          <TextField
            label="Twitter handle"
            value={site.twitter_handle}
            onChange={(v) => update("twitter_handle", v)}
            placeholder="@yourhandle"
          />
        </div>
      </section>

      <hr className="border-slate-800" />

      <section>
        <SectionHeader
          title="Indexing"
          description="Control what search engines can see and crawl."
        />
        <div className="bg-slate-900 border border-slate-800 rounded-lg px-4">
          <div className="flex items-start justify-between gap-4 py-3">
            <div className="flex-1">
              <p className="text-sm text-white font-medium">Generate sitemap.xml</p>
              <p className="text-xs text-slate-500 mt-0.5">
                Build a sitemap from all pages on every deploy.
              </p>
            </div>
            <Toggle
              checked={site.sitemap_enabled}
              onChange={(v) => update("sitemap_enabled", v)}
            />
          </div>
        </div>
        <div className="mt-4 space-y-4">
          <TextField
            label="Default robots directive"
            hint="Per-page values override this."
            mono
            value={site.default_robots}
            onChange={(v) => update("default_robots", v)}
            placeholder="index,follow"
          />
          <TextAreaField
            label="robots.txt contents"
            rows={5}
            mono
            value={site.robots_txt}
            onChange={(v) => update("robots_txt", v)}
          />
        </div>
      </section>

      <hr className="border-slate-800" />

      <section>
        <SectionHeader
          title="Search console verification"
          description="Meta tags rendered in <head> for ownership verification."
        />
        <div className="grid grid-cols-2 gap-4">
          <TextField
            label="Google site verification"
            mono
            value={site.google_verification}
            onChange={(v) => update("google_verification", v)}
            placeholder="abc123..."
          />
          <TextField
            label="Bing site verification"
            mono
            value={site.bing_verification}
            onChange={(v) => update("bing_verification", v)}
            placeholder="abc123..."
          />
        </div>
      </section>
    </div>
  );
}

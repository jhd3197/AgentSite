export const TITLE_MIN = 30;
export const TITLE_MAX = 60;
export const DESC_MIN = 70;
export const DESC_MAX = 160;

export const DEFAULT_PAGE_SEO = {
  title: "",
  description: "",
  og_title: "",
  og_description: "",
  og_image: "",
  canonical: "",
  robots: "index,follow",
  keywords: "",
  twitter_card: "summary_large_image",
};

function lengthCheck(label, value, min, max) {
  const len = value.length;
  return {
    label,
    ok: len >= min && len <= max,
    warn: len > 0 && (len < min || len > max),
    msg:
      len === 0
        ? "Missing"
        : len < min
        ? `Too short (${len})`
        : len > max
        ? `Too long (${len})`
        : `${len} chars`,
  };
}

export function getPageSeo(pageSeo, slug) {
  return { ...DEFAULT_PAGE_SEO, ...(pageSeo[slug] || {}) };
}

export function scorePageSeo(seo, page) {
  const t = seo.title || page.title || "";
  const checks = [
    lengthCheck("Title length", t, TITLE_MIN, TITLE_MAX),
    lengthCheck("Meta description", seo.description || "", DESC_MIN, DESC_MAX),
    {
      label: "Open Graph image",
      ok: !!seo.og_image,
      warn: false,
      msg: seo.og_image ? "Set" : "Missing",
    },
    {
      label: "Canonical URL",
      ok: !!seo.canonical,
      warn: false,
      msg: seo.canonical ? "Set" : "Missing",
    },
    {
      label: "Robots directive",
      ok: !!seo.robots,
      warn: false,
      msg: seo.robots || "Missing",
    },
  ];
  const passed = checks.filter((c) => c.ok).length;
  const score = Math.round((passed / checks.length) * 100);
  return { score, checks };
}

export function scoreAllPages(pages, pageSeo) {
  return pages.map((page) => ({
    page,
    ...scorePageSeo(getPageSeo(pageSeo, page.slug), page),
  }));
}

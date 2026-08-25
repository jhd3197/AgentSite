export default function SerpPreview({ canonicalBase, page, seo }) {
  const url = `${canonicalBase || "https://yoursite.com"}${
    page.slug === "home" ? "" : "/" + page.slug
  }`;
  const title = seo.title || page.title || "Untitled page";
  const desc =
    seo.description ||
    "No meta description set. Search engines will generate one from page content.";
  return (
    <div className="bg-white rounded-lg p-4 font-sans">
      <div className="flex items-center gap-1.5 mb-1 text-xs text-slate-700">
        <div className="w-4 h-4 bg-slate-200 rounded-full" />
        <span className="font-medium">
          {new URL(url.replace(/\/$/, "") || "https://yoursite.com").host}
        </span>
        <span className="text-slate-400">›</span>
        <span className="text-slate-500 truncate">{page.slug}</span>
      </div>
      <h3 className="text-[#1a0dab] text-lg leading-snug hover:underline cursor-pointer mb-1 truncate">
        {title}
      </h3>
      <p className="text-sm text-slate-600 leading-snug line-clamp-2">{desc}</p>
    </div>
  );
}

import { Image as ImageIcon } from "@phosphor-icons/react";

export default function SocialPreview({ projectId, page, seo, defaultOg }) {
  const title = seo.og_title || seo.title || page.title;
  const desc = seo.og_description || seo.description;
  const img = seo.og_image || defaultOg;
  const imgSrc = img ? `/preview/${projectId}/assets/${img}` : null;

  return (
    <div className="bg-slate-100 rounded-lg overflow-hidden border border-slate-200">
      <div className="aspect-[1.91/1] bg-gradient-to-br from-slate-200 to-slate-300 flex items-center justify-center">
        {imgSrc ? (
          <img src={imgSrc} alt="" className="w-full h-full object-cover" />
        ) : (
          <div className="text-slate-400 flex flex-col items-center gap-2">
            <ImageIcon size={32} />
            <span className="text-xs">No OG image set</span>
          </div>
        )}
      </div>
      <div className="p-3 bg-slate-50">
        <p className="text-[10px] uppercase text-slate-500 tracking-wide mb-0.5">
          yoursite.com
        </p>
        <p className="text-sm font-semibold text-slate-900 leading-snug line-clamp-1">
          {title || "Untitled"}
        </p>
        <p className="text-xs text-slate-600 line-clamp-2 mt-0.5">
          {desc || "No description"}
        </p>
      </div>
    </div>
  );
}

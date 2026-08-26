export default function LayoutThumb({ type, active }) {
  const bar = active ? "bg-brand-400" : "bg-slate-600";
  const area = active ? "bg-brand-500/20" : "bg-slate-800";
  const line = active ? "bg-brand-500/30" : "bg-slate-700";

  if (type === "top-nav") {
    return (
      <div className="w-full h-14 rounded bg-slate-950 border border-slate-800 overflow-hidden">
        <div className={`h-2.5 ${bar} w-full`} />
        <div className="p-1.5 space-y-1">
          <div className={`h-1 ${line} w-3/4 rounded-full`} />
          <div className={`h-1 ${line} w-1/2 rounded-full`} />
          <div className={`h-4 ${area} rounded`} />
        </div>
      </div>
    );
  }

  if (type === "sidebar") {
    return (
      <div className="w-full h-14 rounded bg-slate-950 border border-slate-800 overflow-hidden flex">
        <div className={`w-4 ${bar} shrink-0`} />
        <div className="flex-1 p-1.5 space-y-1">
          <div className={`h-1 ${line} w-3/4 rounded-full`} />
          <div className={`h-1 ${line} w-1/2 rounded-full`} />
          <div className={`h-4 ${area} rounded`} />
        </div>
      </div>
    );
  }

  if (type === "minimal") {
    return (
      <div className="w-full h-14 rounded bg-slate-950 border border-slate-800 overflow-hidden">
        <div className="h-2.5 flex items-center justify-between px-1.5">
          <div className={`w-2 h-1 ${bar} rounded`} />
          <div className="flex gap-0.5">
            <div className={`w-1.5 h-0.5 ${bar} rounded-full`} />
            <div className={`w-1.5 h-0.5 ${bar} rounded-full`} />
          </div>
        </div>
        <div className="px-1.5 space-y-1">
          <div className={`h-1 ${line} w-1/2 rounded-full mx-auto`} />
          <div className={`h-5 ${area} rounded`} />
        </div>
      </div>
    );
  }

  return (
    <div className="w-full h-14 rounded bg-slate-950 border border-slate-800 overflow-hidden">
      <div className="h-2.5 flex items-center justify-center gap-1 px-1">
        <div className={`w-2 h-0.5 ${bar} rounded-full`} />
        <div className={`w-1.5 h-1 ${bar} rounded`} />
        <div className={`w-2 h-0.5 ${bar} rounded-full`} />
      </div>
      <div className="px-1.5 space-y-1">
        <div className={`h-1 ${line} w-1/2 rounded-full mx-auto`} />
        <div className={`h-5 ${area} rounded`} />
      </div>
    </div>
  );
}

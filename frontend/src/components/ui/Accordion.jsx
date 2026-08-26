import { CaretDown, CaretRight } from "@phosphor-icons/react";

export default function Accordion({
  open,
  onToggle,
  icon: Icon,
  title,
  children,
  contentClassName = "",
}) {
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-lg overflow-hidden">
      <button
        onClick={onToggle}
        className="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-slate-800/50 transition-colors"
      >
        {Icon && <Icon size={16} className="text-slate-500 shrink-0" />}
        <span className="text-sm flex-1 min-w-0 truncate">{title}</span>
        {open ? (
          <CaretDown size={14} className="text-slate-500 shrink-0" />
        ) : (
          <CaretRight size={14} className="text-slate-500 shrink-0" />
        )}
      </button>
      {open && (
        <div className={`border-t border-slate-800 ${contentClassName}`}>{children}</div>
      )}
    </div>
  );
}

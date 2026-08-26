export default function TabButton({ active, onClick, icon: Icon, children, count }) {
  return (
    <button
      onClick={onClick}
      className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors -mb-px ${
        active
          ? "border-brand-500 text-white"
          : "border-transparent text-slate-500 hover:text-slate-300"
      }`}
    >
      <Icon size={16} />
      {children}
      {count != null && (
        <span className="text-[10px] font-semibold bg-slate-800 text-slate-400 px-1.5 py-0.5 rounded">
          {count}
        </span>
      )}
    </button>
  );
}

const VARIANTS = {
  primary:
    "bg-white text-slate-950 hover:bg-slate-100 shadow-lg shadow-white/10 disabled:opacity-60 disabled:cursor-not-allowed",
  brand:
    "bg-brand-600 hover:bg-brand-500 text-white disabled:opacity-50 disabled:cursor-not-allowed",
  secondary:
    "bg-slate-800 hover:bg-slate-700 text-slate-200 disabled:opacity-50 disabled:cursor-not-allowed",
  ghost:
    "text-brand-400 hover:text-brand-300 disabled:opacity-50 disabled:cursor-not-allowed",
};

const SIZES = {
  sm: "px-3 py-2 text-xs rounded-md gap-1.5",
  md: "px-4 py-2 text-sm rounded-lg gap-2",
  lg: "px-5 py-2.5 text-sm rounded-lg gap-2",
};

export default function Button({
  variant = "primary",
  size = "md",
  className = "",
  children,
  ...rest
}) {
  return (
    <button
      className={`inline-flex items-center justify-center font-semibold transition-colors ${
        VARIANTS[variant] || VARIANTS.primary
      } ${SIZES[size] || SIZES.md} ${className}`}
      {...rest}
    >
      {children}
    </button>
  );
}

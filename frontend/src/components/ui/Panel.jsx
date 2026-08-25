const ROUNDED = {
  lg: "rounded-lg",
  xl: "rounded-xl",
  none: "",
};

export default function Panel({ rounded = "xl", className = "", children, ...rest }) {
  return (
    <div
      className={`bg-slate-900 border border-slate-800 ${ROUNDED[rounded] || ROUNDED.xl} ${className}`}
      {...rest}
    >
      {children}
    </div>
  );
}

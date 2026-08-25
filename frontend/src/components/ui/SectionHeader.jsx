export default function SectionHeader({ title, description, variant = "title", as, className = "" }) {
  if (variant === "label") {
    const Tag = as || "h2";
    return (
      <Tag
        className={`text-sm font-semibold text-slate-400 uppercase tracking-wider ${
          className || "mb-4"
        }`}
      >
        {title}
      </Tag>
    );
  }
  const Tag = as || "h3";
  return (
    <div className={`mb-5 ${className}`}>
      <Tag className="text-lg font-semibold text-white">{title}</Tag>
      {description && <p className="text-xs text-slate-500 mt-1">{description}</p>}
    </div>
  );
}

import Field from "./Field";

const SIZES = {
  sm: "border border-slate-800 rounded-md py-1.5 px-2.5",
  md: "border border-slate-700 rounded-lg py-2 px-3",
};

export default function TextField({
  label,
  value,
  onChange,
  placeholder,
  mono,
  size = "md",
  type = "text",
  className = "",
  ...rest
}) {
  return (
    <Field label={label} {...rest}>
      <input
        type={type}
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className={`w-full bg-slate-950 ${SIZES[size]} text-white text-sm focus:border-brand-500 focus:outline-none ${
          mono ? "font-mono text-xs" : ""
        } ${className}`}
      />
    </Field>
  );
}

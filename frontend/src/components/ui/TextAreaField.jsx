import Field from "./Field";

export default function TextAreaField({
  label,
  value,
  onChange,
  placeholder,
  rows = 3,
  mono,
  hint,
  counter,
}) {
  return (
    <Field label={label} hint={hint} counter={counter}>
      <textarea
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        rows={rows}
        className={`w-full bg-slate-950 border border-slate-700 text-white text-sm rounded-lg py-2 px-3 focus:border-brand-500 focus:outline-none resize-none ${
          mono ? "font-mono text-xs" : ""
        }`}
      />
    </Field>
  );
}

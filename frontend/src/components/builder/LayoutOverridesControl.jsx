import { useEffect, useRef, useState } from "react";
import { Layout, X } from "@phosphor-icons/react";
import { updatePage } from "../../api/projects";

// Only the layout-ish StyleSpec fields are page-overridable from the UI.
const FIELDS = [
  {
    key: "layout_style",
    label: "Layout",
    type: "select",
    options: ["top-nav", "sidebar", "minimal", "centered"],
  },
  {
    key: "nav_position",
    label: "Nav position",
    type: "select",
    options: ["sticky", "fixed", "static"],
  },
  {
    key: "footer_style",
    label: "Footer",
    type: "select",
    options: ["standard", "minimal", "none"],
  },
  { key: "max_width", label: "Max width", type: "text" },
  { key: "container_padding", label: "Padding", type: "text" },
  { key: "section_gap", label: "Section gap", type: "text" },
];

export default function LayoutOverridesControl({ projectId, page, project, onSaved }) {
  const [open, setOpen] = useState(false);
  const [overrides, setOverrides] = useState({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const panelRef = useRef(null);

  const spec = project?.style_spec || {};
  const activeCount = Object.keys(page?.layout_overrides || {}).length;

  // Sync local state from the page whenever it changes (or panel opens).
  useEffect(() => {
    setOverrides({ ...(page?.layout_overrides || {}) });
    setError(null);
  }, [page?.layout_overrides, open]);

  // Close on outside click.
  useEffect(() => {
    if (!open) return;
    const onDown = (e) => {
      if (panelRef.current && !panelRef.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  const setField = (key, value) => {
    setOverrides((prev) => {
      const next = { ...prev };
      if (value === "" || value == null) delete next[key];
      else next[key] = value;
      return next;
    });
  };

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      await updatePage(projectId, page.slug, {
        layout_overrides: Object.keys(overrides).length ? overrides : null,
      });
      onSaved?.();
      setOpen(false);
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  };

  if (!page) return null;

  return (
    <div className="relative" ref={panelRef}>
      <button
        onClick={() => setOpen((v) => !v)}
        className={`relative flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-xs font-medium transition-colors ${
          activeCount
            ? "border-brand-500/60 text-brand-300 bg-brand-500/10"
            : "border-slate-800 text-slate-500 hover:text-slate-300"
        }`}
        title={
          activeCount
            ? `${activeCount} layout override${activeCount > 1 ? "s" : ""} active on this page`
            : "Per-page layout overrides"
        }
      >
        <Layout size={14} />
        Layout
        {activeCount > 0 && (
          <span className="absolute -top-1 -right-1 w-2 h-2 rounded-full bg-brand-400" />
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-2 w-72 rounded-lg border border-slate-800 bg-slate-900 shadow-xl z-50 p-3">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-semibold text-slate-200">Page layout</span>
            <span className="text-[10px] text-slate-500">inherits project defaults</span>
          </div>

          <div className="space-y-2">
            {FIELDS.map((f) => {
              const overridden = overrides[f.key] != null;
              return (
                <div key={f.key} className="flex items-center gap-2">
                  <label className="w-24 shrink-0 text-[11px] text-slate-400">{f.label}</label>
                  {f.type === "select" ? (
                    <select
                      value={overrides[f.key] ?? ""}
                      onChange={(e) => setField(f.key, e.target.value)}
                      className={`flex-1 min-w-0 bg-slate-950 border rounded px-1.5 py-1 text-[11px] outline-none focus:border-brand-500 ${
                        overridden
                          ? "border-brand-500/50 text-slate-200"
                          : "border-slate-800 text-slate-500"
                      }`}
                    >
                      <option value="">default ({spec[f.key] ?? "—"})</option>
                      {f.options.map((opt) => (
                        <option key={opt} value={opt}>
                          {opt}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <input
                      type="text"
                      value={overrides[f.key] ?? ""}
                      placeholder={spec[f.key] ?? ""}
                      onChange={(e) => setField(f.key, e.target.value)}
                      className={`flex-1 min-w-0 bg-slate-950 border rounded px-1.5 py-1 text-[11px] outline-none focus:border-brand-500 placeholder:text-slate-600 ${
                        overridden
                          ? "border-brand-500/50 text-slate-200"
                          : "border-slate-800 text-slate-300"
                      }`}
                    />
                  )}
                  <button
                    onClick={() => setField(f.key, null)}
                    disabled={!overridden}
                    className={`shrink-0 p-0.5 rounded transition-colors ${
                      overridden
                        ? "text-slate-400 hover:text-white"
                        : "text-slate-800 cursor-default"
                    }`}
                    title="Reset to project default"
                  >
                    <X size={11} />
                  </button>
                </div>
              );
            })}
          </div>

          {error && <p className="mt-2 text-[11px] text-red-400">{error}</p>}

          <div className="mt-3 flex items-center justify-between">
            <button
              onClick={() => setOverrides({})}
              className="text-[11px] text-slate-500 hover:text-slate-300 transition-colors"
            >
              Reset all
            </button>
            <button
              onClick={handleSave}
              disabled={saving}
              className="bg-brand-600 hover:bg-brand-500 disabled:opacity-50 text-white px-3 py-1 rounded text-[11px] font-semibold transition-colors"
            >
              {saving ? "Saving…" : "Save"}
            </button>
          </div>
          <p className="mt-2 text-[10px] text-slate-600">
            Applies to the next generation of this page.
          </p>
        </div>
      )}
    </div>
  );
}

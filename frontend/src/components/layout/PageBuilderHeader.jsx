import { useNavigate } from "react-router-dom";
import {
  ArrowLeft,
  Eye,
  Code as CodeIcon,
  Export,
} from "@phosphor-icons/react";
import DeviceSwitcher from "../builder/DeviceSwitcher";
import VersionSelector from "../builder/VersionSelector";
import LayoutOverridesControl from "../builder/LayoutOverridesControl";
import { getExportUrl } from "../../api/assets";

export default function PageBuilderHeader({
  projectId,
  page,
  project,
  device,
  onDeviceChange,
  versions,
  activeVersion,
  onVersionChange,
  viewMode,
  onViewModeChange,
  onPageUpdated,
}) {
  const navigate = useNavigate();

  return (
    <header className="h-14 border-b border-slate-800 bg-slate-950 flex items-center justify-between px-4 shrink-0 z-20">
      <div className="flex items-center gap-4 min-w-0">
        <button
          onClick={() => navigate(`/project/${projectId}`)}
          className="text-slate-500 hover:text-white transition-colors flex items-center gap-1 text-sm shrink-0"
        >
          <ArrowLeft size={14} /> Back
        </button>
        <div className="h-4 w-px bg-slate-800" />
        <span className="font-semibold text-white truncate">
          {page?.title || "..."}
        </span>
      </div>

      <DeviceSwitcher active={device} onChange={onDeviceChange} />

      <div className="flex items-center gap-3">
        <LayoutOverridesControl
          projectId={projectId}
          page={page}
          project={project}
          onSaved={onPageUpdated}
        />

        {versions?.length > 0 && (
          <VersionSelector
            versions={versions}
            active={activeVersion}
            onChange={onVersionChange}
          />
        )}

        {/* Preview / Code toggle */}
        <div className="flex items-center rounded-lg border border-slate-800 overflow-hidden">
          <button
            onClick={() => onViewModeChange("preview")}
            className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium transition-colors ${
              viewMode === "preview"
                ? "bg-slate-800 text-white"
                : "text-slate-500 hover:text-slate-300"
            }`}
            title="Preview"
          >
            <Eye size={14} />
            Preview
          </button>
          <button
            onClick={() => onViewModeChange("code")}
            className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium transition-colors ${
              viewMode === "code"
                ? "bg-slate-800 text-white"
                : "text-slate-500 hover:text-slate-300"
            }`}
            title="Code"
          >
            <CodeIcon size={14} />
            Code
          </button>
        </div>

        <a
          href={getExportUrl(projectId)}
          className="bg-brand-600 hover:bg-brand-500 text-white px-4 py-1.5 rounded-lg text-sm font-semibold shadow-lg shadow-brand-500/20 flex items-center gap-2 transition-colors"
        >
          Export
          <Export size={14} />
        </a>
      </div>
    </header>
  );
}

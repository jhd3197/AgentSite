import { useNavigate } from "react-router-dom";
import { DotsThreeVertical } from "@phosphor-icons/react";
import Badge from "../shared/Badge";

function BrowserMockup() {
  return (
    <div className="absolute inset-4 bg-slate-950 rounded-t-lg border border-slate-700 shadow-2xl opacity-75">
      <div className="h-4 bg-slate-800 border-b border-slate-700 flex items-center px-2 gap-1">
        <div className="w-2 h-2 rounded-full bg-red-500/50" />
        <div className="w-2 h-2 rounded-full bg-yellow-500/50" />
        <div className="w-2 h-2 rounded-full bg-green-500/50" />
      </div>
      <div className="p-4 flex flex-col gap-2">
        <div className="w-1/2 h-2 bg-slate-700 rounded" />
        <div className="w-3/4 h-2 bg-slate-800 rounded" />
        <div className="grid grid-cols-2 gap-2 mt-2">
          <div className="h-12 bg-slate-800 rounded" />
          <div className="h-12 bg-slate-800 rounded" />
        </div>
      </div>
    </div>
  );
}

function GeneratingView({ project }) {
  return (
    <>
      <div className="h-40 bg-slate-950 relative overflow-hidden flex items-center justify-center">
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,_var(--tw-gradient-stops))] from-indigo-900/40 via-slate-950 to-slate-950" />
        <div className="text-center relative z-10">
          <div className="text-3xl text-brand-500 animate-bounce mb-2">&#x2699;</div>
          <p className="text-xs font-medium text-brand-300">Agents working...</p>
        </div>
      </div>
      <div className="p-5 flex-1 flex flex-col justify-between">
        <div>
          <h3 className="text-lg font-semibold text-white group-hover:text-brand-400 transition-colors">
            {project.name}
          </h3>
          <p className="text-xs text-slate-500 font-mono">Generating...</p>
        </div>
        <div className="w-full bg-slate-800 rounded-full h-1.5 mt-4 overflow-hidden">
          <div className="bg-brand-500 h-1.5 rounded-full w-2/3 shadow-[0_0_10px_rgba(99,102,241,0.5)] animate-pulse" />
        </div>
      </div>
    </>
  );
}

function getStatus(project) {
  // Simple heuristic: if project has style_spec, it's been through at least one generation
  if (project.style_spec) return "live";
  return "draft";
}

function timeSince(dateStr) {
  const seconds = Math.floor((Date.now() - new Date(dateStr).getTime()) / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

export default function ProjectCard({ project, onDelete }) {
  const navigate = useNavigate();
  const status = getStatus(project);

  return (
    <div
      onClick={() => navigate(`/project/${project.id}`)}
      className="group bg-slate-900 border border-slate-800 rounded-xl overflow-hidden hover:border-slate-600 hover:shadow-xl hover:shadow-brand-500/10 transition-all duration-300 flex flex-col h-[300px] cursor-pointer"
    >
      <div className="h-40 bg-slate-800 relative overflow-hidden group-hover:opacity-90 transition-opacity">
        <BrowserMockup />
        <div className="absolute top-3 right-3 flex items-center gap-1.5">
          {project.mode === "project" && <Badge status="active">Project</Badge>}
          <Badge status={status}>{status}</Badge>
        </div>
      </div>

      <div className="p-5 flex-1 flex flex-col justify-between">
        <div>
          <div className="flex justify-between items-start mb-1">
            <h3 className="text-lg font-semibold text-white group-hover:text-brand-400 transition-colors">
              {project.name}
            </h3>
            <button
              onClick={(e) => {
                e.stopPropagation();
                onDelete?.(project.id);
              }}
              className="text-slate-500 hover:text-white"
            >
              <DotsThreeVertical weight="bold" size={18} />
            </button>
          </div>
          <p className="text-xs text-slate-500 font-mono truncate">
            {project.description || project.id}
          </p>
        </div>

        <div className="flex items-center justify-between pt-4 border-t border-slate-800 mt-2">
          <div className="flex items-center gap-2">
            {status === "live" ? (
              <span className="flex h-2 w-2 relative">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75" />
                <span className="relative inline-flex rounded-full h-2 w-2 bg-green-500" />
              </span>
            ) : (
              <span className="w-2 h-2 rounded-full bg-slate-600" />
            )}
            <span className="text-xs text-slate-400">
              {project.model || "No model"}
            </span>
          </div>
          <span className="text-xs text-slate-500">
            {timeSince(project.updated_at)}
          </span>
        </div>
      </div>
    </div>
  );
}

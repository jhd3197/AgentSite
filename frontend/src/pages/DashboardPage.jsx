import { useState, useMemo, useEffect } from "react";
import { useSearchParams } from "react-router-dom";
import { Lightning, Code } from "@phosphor-icons/react";
import useProjects from "../hooks/useProjects";
import { useApp } from "../context/AppContext";
import { listTemplates } from "../api/templates";
import ProjectCard from "../components/dashboard/ProjectCard";
import CreateProjectCard from "../components/dashboard/CreateProjectCard";
import ProjectFilterBar from "../components/dashboard/ProjectFilterBar";
import TemplateGallery from "../components/dashboard/TemplateGallery";
import Modal from "../components/shared/Modal";
import Spinner from "../components/shared/Spinner";

export default function DashboardPage() {
  const { projects, loading, create, remove } = useProjects();
  const { search } = useApp();
  const [searchParams, setSearchParams] = useSearchParams();
  const [filter, setFilter] = useState("All");
  const [showCreate, setShowCreate] = useState(false);

  useEffect(() => {
    if (searchParams.get("new") === "1") {
      setShowCreate(true);
      setSearchParams({}, { replace: true });
    }
  }, [searchParams, setSearchParams]);
  const [newName, setNewName] = useState("");
  const [newDesc, setNewDesc] = useState("");
  const [newMode, setNewMode] = useState("mockup");
  const [newTemplateId, setNewTemplateId] = useState("static-multipage");
  const [templates, setTemplates] = useState(null); // null = not loaded yet
  const [creating, setCreating] = useState(false);

  // Lazy-load workspace templates the first time "Project" mode is picked.
  useEffect(() => {
    if (!showCreate || newMode !== "project" || templates !== null) return;
    let cancelled = false;
    listTemplates()
      .then((data) => { if (!cancelled) setTemplates(data || []); })
      .catch(() => { if (!cancelled) setTemplates([]); });
    return () => { cancelled = true; };
  }, [showCreate, newMode, templates]);

  // Keep the selected template valid once the list arrives.
  useEffect(() => {
    if (!templates || templates.length === 0) return;
    if (!templates.some((t) => t.id === newTemplateId)) {
      setNewTemplateId(templates[0].id);
    }
  }, [templates, newTemplateId]);

  const filtered = useMemo(() => {
    let list = projects;
    if (search) {
      const q = search.toLowerCase();
      list = list.filter(
        (p) =>
          p.name.toLowerCase().includes(q) ||
          (p.description || "").toLowerCase().includes(q)
      );
    }
    if (filter === "Live") {
      list = list.filter((p) => p.style_spec);
    } else if (filter === "Drafts") {
      list = list.filter((p) => !p.style_spec);
    }
    return list;
  }, [projects, search, filter]);

  const handleCreate = async () => {
    if (!newName.trim()) return;
    setCreating(true);
    try {
      const payload = { name: newName.trim(), description: newDesc.trim() };
      if (newMode === "project") {
        payload.mode = "project";
        payload.template_id = newTemplateId;
      }
      await create(payload);
      setShowCreate(false);
      setNewName("");
      setNewDesc("");
      setNewMode("mockup");
      setNewTemplateId("static-multipage");
    } catch {}
    setCreating(false);
  };

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <Spinner size={32} />
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto p-8">
      <div className="max-w-7xl mx-auto">
        <div className="flex items-end justify-between mb-8">
          <div>
            <h1 className="text-2xl font-bold text-white mb-1">Projects</h1>
            <p className="text-slate-500 text-sm">
              Manage your AI-generated sites and deployments.
            </p>
          </div>
          <ProjectFilterBar active={filter} onChange={setFilter} />
        </div>

        <TemplateGallery
          onPick={(t) => {
            setNewName(t.name);
            setNewDesc(t.prompt);
            setShowCreate(true);
          }}
        />

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          <CreateProjectCard onClick={() => setShowCreate(true)} />
          {filtered.map((project) => (
            <ProjectCard
              key={project.id}
              project={project}
              onDelete={(id) => {
                if (confirm("Delete this project?")) remove(id);
              }}
            />
          ))}
        </div>

        {filtered.length === 0 && !loading && (
          <p className="text-center text-slate-500 mt-12">
            No projects found. Create one to get started.
          </p>
        )}
      </div>

      {showCreate && (
        <Modal title="Create New Project" onClose={() => setShowCreate(false)}>
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-1">
                Project Name
              </label>
              <input
                type="text"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                placeholder="My Awesome Site"
                className="w-full bg-slate-950 border border-slate-700 text-white text-sm rounded-lg py-2 px-3 focus:border-brand-500 focus:outline-none"
                autoFocus
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-1">
                Description
              </label>
              <textarea
                value={newDesc}
                onChange={(e) => setNewDesc(e.target.value)}
                placeholder="A brief description..."
                rows={3}
                className="w-full bg-slate-950 border border-slate-700 text-white text-sm rounded-lg py-2 px-3 focus:border-brand-500 focus:outline-none resize-none"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-1">
                Type
              </label>
              <div className="grid grid-cols-2 gap-2">
                <button
                  type="button"
                  onClick={() => setNewMode("mockup")}
                  className={`text-left rounded-lg border p-3 transition-colors ${
                    newMode === "mockup"
                      ? "border-brand-500 bg-brand-500/10"
                      : "border-slate-700 bg-slate-950 hover:border-slate-600"
                  }`}
                >
                  <div className="flex items-center gap-1.5 mb-1">
                    <Lightning
                      size={14}
                      weight="fill"
                      className={newMode === "mockup" ? "text-brand-400" : "text-slate-500"}
                    />
                    <span className="text-sm font-semibold text-white">Mockup</span>
                  </div>
                  <p className="text-xs text-slate-500 leading-snug">
                    Single page, fastest. Best for quick designs.
                  </p>
                </button>
                <button
                  type="button"
                  onClick={() => setNewMode("project")}
                  className={`text-left rounded-lg border p-3 transition-colors ${
                    newMode === "project"
                      ? "border-brand-500 bg-brand-500/10"
                      : "border-slate-700 bg-slate-950 hover:border-slate-600"
                  }`}
                >
                  <div className="flex items-center gap-1.5 mb-1">
                    <Code
                      size={14}
                      weight="fill"
                      className={newMode === "project" ? "text-brand-400" : "text-slate-500"}
                    />
                    <span className="text-sm font-semibold text-white">Project</span>
                  </div>
                  <p className="text-xs text-slate-500 leading-snug">
                    Real codebase: multi-file workspace, downloadable &amp; runnable.
                  </p>
                </button>
              </div>
            </div>
            {newMode === "project" && (
              <div>
                <label className="block text-sm font-medium text-slate-300 mb-1">
                  Template
                </label>
                {templates === null ? (
                  <p className="text-xs text-slate-500 py-2">Loading templates…</p>
                ) : templates.length === 0 ? (
                  <p className="text-xs text-slate-500 py-2">
                    Could not load templates — using <span className="font-mono">static-multipage</span>.
                  </p>
                ) : (
                  <div className="space-y-2">
                    {templates.map((t) => (
                      <button
                        key={t.id}
                        type="button"
                        onClick={() => setNewTemplateId(t.id)}
                        className={`w-full text-left rounded-lg border p-3 transition-colors flex items-start gap-2.5 ${
                          newTemplateId === t.id
                            ? "border-brand-500 bg-brand-500/10"
                            : "border-slate-700 bg-slate-950 hover:border-slate-600"
                        }`}
                      >
                        <span
                          className={`mt-0.5 w-3.5 h-3.5 rounded-full border-2 shrink-0 flex items-center justify-center ${
                            newTemplateId === t.id ? "border-brand-500" : "border-slate-600"
                          }`}
                        >
                          {newTemplateId === t.id && (
                            <span className="w-1.5 h-1.5 rounded-full bg-brand-500" />
                          )}
                        </span>
                        <span className="flex-1 min-w-0">
                          <span className="flex items-center justify-between gap-2">
                            <span className="text-sm font-medium text-white">{t.name}</span>
                            {t.kind && (
                              <span className="text-[10px] font-mono text-slate-500 uppercase">
                                {t.kind}
                              </span>
                            )}
                          </span>
                          <span className="block text-xs text-slate-500 leading-snug mt-0.5">
                            {t.description}
                          </span>
                        </span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
            <button
              onClick={handleCreate}
              disabled={!newName.trim() || creating}
              className="w-full bg-white text-slate-950 py-2 rounded-lg text-sm font-semibold hover:bg-slate-200 transition-colors disabled:opacity-50"
            >
              {creating ? "Creating..." : "Create Project"}
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}

import { useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { Plus, CaretRight, Globe, UploadSimple, MapTrifold } from "@phosphor-icons/react";
import useProject from "../hooks/useProject";
import { importHtml, importFromUrl } from "../api/importer";
import PageCard from "../components/project/PageCard";
import CreatePageCard from "../components/project/CreatePageCard";
import BrandIdentityPanel from "../components/project/BrandIdentityPanel";
import Badge from "../components/shared/Badge";
import Modal from "../components/shared/Modal";
import Spinner from "../components/shared/Spinner";

export default function ProjectPage() {
  const { projectId } = useParams();
  const navigate = useNavigate();
  const { project, pages, loading, refresh, createPage, removePage } =
    useProject(projectId);
  const [showCreate, setShowCreate] = useState(false);
  const [newTitle, setNewTitle] = useState("");
  const [newSlug, setNewSlug] = useState("");
  const [creating, setCreating] = useState(false);

  // Import modal state
  const [showImport, setShowImport] = useState(false);
  const [importTab, setImportTab] = useState("paste"); // "paste" | "url"
  const [importTitle, setImportTitle] = useState("");
  const [importSlug, setImportSlug] = useState("");
  const [importHtmlContent, setImportHtmlContent] = useState("");
  const [importUrlValue, setImportUrlValue] = useState("");
  const [importing, setImporting] = useState(false);
  const [importError, setImportError] = useState("");

  // Rename modal state
  const [renaming, setRenaming] = useState(null); // page object or null
  const [renameTitle, setRenameTitle] = useState("");
  const [renameSlug, setRenameSlug] = useState("");
  const [renameSaving, setRenameSaving] = useState(false);

  const handleCreate = async () => {
    if (!newTitle.trim()) return;
    setCreating(true);
    try {
      const slug =
        newSlug.trim() ||
        newTitle
          .trim()
          .toLowerCase()
          .replace(/[^a-z0-9]+/g, "-")
          .replace(/(^-|-$)/g, "");
      await createPage({ title: newTitle.trim(), slug });
      setShowCreate(false);
      setNewTitle("");
      setNewSlug("");
    } catch {}
    setCreating(false);
  };

  const deriveSlug = (title, slug) =>
    slug.trim() ||
    title
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/(^-|-$)/g, "");

  const resetImport = () => {
    setShowImport(false);
    setImportTab("paste");
    setImportTitle("");
    setImportSlug("");
    setImportHtmlContent("");
    setImportUrlValue("");
    setImportError("");
  };

  const handleImport = async () => {
    const slug = deriveSlug(importTitle, importSlug);
    if (!slug) return;
    if (importTab === "paste" && !importHtmlContent.trim()) return;
    if (importTab === "url" && !importUrlValue.trim()) return;
    setImporting(true);
    setImportError("");
    try {
      const data = { slug, title: importTitle.trim() };
      if (importTab === "paste") {
        await importHtml(projectId, { ...data, html: importHtmlContent });
      } else {
        await importFromUrl(projectId, { ...data, url: importUrlValue.trim() });
      }
      resetImport();
      await refresh();
    } catch (err) {
      setImportError(err.message || "Import failed");
    }
    setImporting(false);
  };

  const handleDuplicate = async (page) => {
    const baseSlug = page.slug.replace(/-copy(-\d+)?$/, "");
    const existingSlugs = new Set(pages.map((p) => p.slug));
    let slug = `${baseSlug}-copy`;
    let n = 2;
    while (existingSlugs.has(slug)) {
      slug = `${baseSlug}-copy-${n++}`;
    }
    await createPage({ title: `${page.title} (Copy)`, slug });
  };

  const handleRenameOpen = (page) => {
    setRenaming(page);
    setRenameTitle(page.title);
    setRenameSlug(page.slug);
  };

  const handleRenameSave = async () => {
    if (!renameTitle.trim() || !renaming) return;
    setRenameSaving(true);
    try {
      // Delete old and create new since there's no update endpoint yet
      const slug =
        renameSlug.trim() ||
        renameTitle
          .trim()
          .toLowerCase()
          .replace(/[^a-z0-9]+/g, "-")
          .replace(/(^-|-$)/g, "");
      await removePage(renaming.slug);
      await createPage({ title: renameTitle.trim(), slug });
      setRenaming(null);
    } catch {}
    setRenameSaving(false);
  };

  const handleSetHome = async (page) => {
    // Duplicate the page content to the "home" slug
    const homeExists = pages.some((p) => p.slug === "home");
    if (
      homeExists &&
      !confirm(
        `This will replace the current homepage with "${page.title}". Continue?`
      )
    )
      return;
    if (homeExists) await removePage("home");
    await createPage({ title: page.title, slug: "home" });
  };

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <Spinner size={32} />
      </div>
    );
  }

  const status = project?.style_spec ? "live" : "draft";

  return (
    <div className="flex-1 overflow-y-auto">
      {/* Breadcrumb header */}
      <div className="h-12 border-b border-slate-800 bg-slate-950/80 backdrop-blur-md flex items-center justify-between px-8 z-20">
        <div className="flex items-center gap-2 text-sm">
          <span className="text-slate-500">Projects</span>
          <CaretRight className="text-slate-600" size={12} />
          <span className="text-white font-medium">
            {project?.name || "..."}
          </span>
          <span className="ml-2">
            <Badge status={status}>{status}</Badge>
          </span>
        </div>
        <div className="flex items-center gap-3">
          <button className="text-slate-400 hover:text-white transition-colors px-3 py-1.5 text-sm font-medium">
            <Globe className="inline mr-1" size={14} />
            Visit Live Site
          </button>
          <a
            href={`/api/projects/${projectId}/export`}
            className="bg-white text-slate-950 px-4 py-2 rounded-lg text-sm font-semibold hover:bg-slate-200 transition-colors shadow-lg shadow-white/5"
          >
            Export Code
          </a>
        </div>
      </div>

      <div className="p-8">
        <div className="max-w-7xl mx-auto grid grid-cols-1 lg:grid-cols-12 gap-8">
          {/* Pages grid */}
          <div className="lg:col-span-8 space-y-6">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-xl font-bold text-white">Pages</h2>
                <p className="text-slate-500 text-sm">
                  Manage the structure of your website.
                </p>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => navigate(`/project/${projectId}/canvas`)}
                  className="flex items-center gap-2 bg-slate-800 hover:bg-slate-700 text-white px-3 py-1.5 rounded-lg text-sm font-medium transition-colors border border-slate-700"
                >
                  <MapTrifold size={14} />
                  Canvas
                </button>
                <button
                  onClick={() => setShowImport(true)}
                  className="flex items-center gap-2 bg-slate-800 hover:bg-slate-700 text-white px-3 py-1.5 rounded-lg text-sm font-medium transition-colors border border-slate-700"
                >
                  <UploadSimple size={14} />
                  Import
                </button>
                <button
                  onClick={() => setShowCreate(true)}
                  className="flex items-center gap-2 bg-brand-600 hover:bg-brand-500 text-white px-3 py-1.5 rounded-lg text-sm font-medium transition-colors shadow-lg shadow-brand-500/20"
                >
                  <Plus size={14} />
                  New Page
                </button>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
              {pages.map((page) => (
                <PageCard
                  key={page.id}
                  page={page}
                  status="draft"
                  onDelete={(slug) => {
                    if (confirm("Delete this page?")) removePage(slug);
                  }}
                  onDuplicate={handleDuplicate}
                  onRename={handleRenameOpen}
                  onSetHome={handleSetHome}
                />
              ))}
              <CreatePageCard onClick={() => setShowCreate(true)} />
            </div>
          </div>

          {/* Brand panel */}
          <div className="lg:col-span-4">
            <BrandIdentityPanel
              project={project}
              onEditBrand={() =>
                navigate(`/project/${projectId}/brand`)
              }
            />
          </div>
        </div>
      </div>

      {showCreate && (
        <Modal title="Add New Page" onClose={() => setShowCreate(false)}>
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-1">
                Page Title
              </label>
              <input
                type="text"
                value={newTitle}
                onChange={(e) => setNewTitle(e.target.value)}
                placeholder="About Us"
                className="w-full bg-slate-950 border border-slate-700 text-white text-sm rounded-lg py-2 px-3 focus:border-brand-500 focus:outline-none"
                autoFocus
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-1">
                URL Slug
              </label>
              <input
                type="text"
                value={newSlug}
                onChange={(e) => setNewSlug(e.target.value)}
                placeholder="about (auto-generated if empty)"
                className="w-full bg-slate-950 border border-slate-700 text-white text-sm rounded-lg py-2 px-3 focus:border-brand-500 focus:outline-none font-mono"
              />
            </div>
            <button
              onClick={handleCreate}
              disabled={!newTitle.trim() || creating}
              className="w-full bg-white text-slate-950 py-2 rounded-lg text-sm font-semibold hover:bg-slate-200 transition-colors disabled:opacity-50"
            >
              {creating ? "Creating..." : "Add Page"}
            </button>
          </div>
        </Modal>
      )}

      {showImport && (
        <Modal title="Import Page" onClose={resetImport}>
          <div className="space-y-4">
            {/* Tabs */}
            <div className="flex gap-1 bg-slate-950 border border-slate-700 rounded-lg p-1">
              {[
                ["paste", "Paste HTML"],
                ["url", "From URL"],
              ].map(([key, label]) => (
                <button
                  key={key}
                  onClick={() => setImportTab(key)}
                  className={`flex-1 py-1.5 rounded-md text-sm font-medium transition-colors ${
                    importTab === key
                      ? "bg-slate-800 text-white"
                      : "text-slate-400 hover:text-white"
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-1">
                Page Title
              </label>
              <input
                type="text"
                value={importTitle}
                onChange={(e) => setImportTitle(e.target.value)}
                placeholder="Imported Page"
                className="w-full bg-slate-950 border border-slate-700 text-white text-sm rounded-lg py-2 px-3 focus:border-brand-500 focus:outline-none"
                autoFocus
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-1">
                URL Slug
              </label>
              <input
                type="text"
                value={importSlug}
                onChange={(e) => setImportSlug(e.target.value)}
                placeholder="imported (auto-generated if empty)"
                className="w-full bg-slate-950 border border-slate-700 text-white text-sm rounded-lg py-2 px-3 focus:border-brand-500 focus:outline-none font-mono"
              />
            </div>
            {importTab === "paste" ? (
              <div>
                <label className="block text-sm font-medium text-slate-300 mb-1">
                  HTML
                </label>
                <textarea
                  value={importHtmlContent}
                  onChange={(e) => setImportHtmlContent(e.target.value)}
                  placeholder="<!DOCTYPE html>..."
                  rows={10}
                  className="w-full bg-slate-950 border border-slate-700 text-white text-sm rounded-lg py-2 px-3 focus:border-brand-500 focus:outline-none font-mono resize-y"
                />
              </div>
            ) : (
              <div>
                <label className="block text-sm font-medium text-slate-300 mb-1">
                  Page URL
                </label>
                <input
                  type="url"
                  value={importUrlValue}
                  onChange={(e) => setImportUrlValue(e.target.value)}
                  placeholder="https://example.com/page"
                  className="w-full bg-slate-950 border border-slate-700 text-white text-sm rounded-lg py-2 px-3 focus:border-brand-500 focus:outline-none font-mono"
                />
              </div>
            )}
            {importError && (
              <p className="text-red-400 text-sm">{importError}</p>
            )}
            <button
              onClick={handleImport}
              disabled={
                importing ||
                !deriveSlug(importTitle, importSlug) ||
                (importTab === "paste"
                  ? !importHtmlContent.trim()
                  : !importUrlValue.trim())
              }
              className="w-full bg-white text-slate-950 py-2 rounded-lg text-sm font-semibold hover:bg-slate-200 transition-colors disabled:opacity-50"
            >
              {importing ? "Importing..." : "Import Page"}
            </button>
          </div>
        </Modal>
      )}

      {renaming && (
        <Modal title="Rename Page" onClose={() => setRenaming(null)}>
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-1">
                Page Title
              </label>
              <input
                type="text"
                value={renameTitle}
                onChange={(e) => setRenameTitle(e.target.value)}
                className="w-full bg-slate-950 border border-slate-700 text-white text-sm rounded-lg py-2 px-3 focus:border-brand-500 focus:outline-none"
                autoFocus
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-1">
                URL Slug
              </label>
              <input
                type="text"
                value={renameSlug}
                onChange={(e) => setRenameSlug(e.target.value)}
                className="w-full bg-slate-950 border border-slate-700 text-white text-sm rounded-lg py-2 px-3 focus:border-brand-500 focus:outline-none font-mono"
              />
            </div>
            <button
              onClick={handleRenameSave}
              disabled={!renameTitle.trim() || renameSaving}
              className="w-full bg-white text-slate-950 py-2 rounded-lg text-sm font-semibold hover:bg-slate-200 transition-colors disabled:opacity-50"
            >
              {renameSaving ? "Saving..." : "Save Changes"}
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}

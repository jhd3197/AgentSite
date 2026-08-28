import { useState, useEffect, useRef, useCallback } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import {
  Plus,
  Minus,
  ArrowsOutSimple,
  CaretRight,
  Kanban,
  MagicWand,
  FileDashed,
  SpinnerGap,
} from "@phosphor-icons/react";
import useProject from "../hooks/useProject";
import * as projectsApi from "../api/projects";
import { startGeneration } from "../api/generate";
import { getPreviewUrl } from "../api/assets";
import Badge from "../components/shared/Badge";
import Modal from "../components/shared/Modal";
import Spinner from "../components/shared/Spinner";

const NODE_W = 320;
const NODE_H = 260; // header (~40) + preview (200) + footer-ish padding
const PREVIEW_H = 200;
const VIRTUAL_W = 1280;
const VIRTUAL_H = 800;
const PREVIEW_SCALE = NODE_W / VIRTUAL_W;
const MIN_ZOOM = 0.25;
const MAX_ZOOM = 1.5;
const GRID_COLS = 3;
const GRID_GAP_X = 400;
const GRID_GAP_Y = 340;
const GRID_ORIGIN_X = 80;
const GRID_ORIGIN_Y = 80;

function defaultPosition(index) {
  return {
    x: GRID_ORIGIN_X + (index % GRID_COLS) * GRID_GAP_X,
    y: GRID_ORIGIN_Y + Math.floor(index / GRID_COLS) * GRID_GAP_Y,
  };
}

export default function ProjectCanvasPage() {
  const { projectId } = useParams();
  const navigate = useNavigate();
  const { project, pages, loading, refresh, createPage } = useProject(projectId);

  const containerRef = useRef(null);
  const [view, setView] = useState({ x: 60, y: 40, scale: 1 });
  // Optimistic positions keyed by slug; falls back to persisted coords, then grid.
  const [positions, setPositions] = useState({});
  const [versions, setVersions] = useState({}); // slug -> latest version_number | null
  const suppressClickRef = useRef(false);

  // Create-page modal state
  const [showCreate, setShowCreate] = useState(false);
  const [newTitle, setNewTitle] = useState("");
  const [newSlug, setNewSlug] = useState("");
  const [creating, setCreating] = useState(false);

  // Generate-all state
  const [gen, setGen] = useState({ active: false, done: 0, total: 0, current: null });

  // Merge positions whenever pages change: optimistic (dragged) positions win,
  // then persisted coords, then a deterministic grid slot by creation order.
  useEffect(() => {
    setPositions((prev) => {
      const next = {};
      const used = new Set();
      for (const page of pages) {
        if (page.canvas_x != null && page.canvas_y != null) {
          used.add(`${page.canvas_x},${page.canvas_y}`);
        }
      }
      let autoIndex = 0;
      for (const page of pages) {
        if (prev[page.slug]) {
          next[page.slug] = prev[page.slug];
          continue;
        }
        if (page.canvas_x != null && page.canvas_y != null) {
          next[page.slug] = { x: page.canvas_x, y: page.canvas_y };
          continue;
        }
        let p = defaultPosition(autoIndex);
        while (used.has(`${p.x},${p.y}`)) {
          autoIndex += 1;
          p = defaultPosition(autoIndex);
        }
        used.add(`${p.x},${p.y}`);
        next[page.slug] = p;
        autoIndex += 1;
      }
      return next;
    });
  }, [pages]);

  // Fetch latest version per page
  useEffect(() => {
    if (!pages.length) return;
    let cancelled = false;
    Promise.all(
      pages.map((p) =>
        projectsApi
          .listVersions(projectId, p.slug)
          .then((vs) => [
            p.slug,
            vs.length ? Math.max(...vs.map((v) => v.version_number)) : null,
          ])
          .catch(() => [p.slug, null])
      )
    ).then((entries) => {
      if (!cancelled) setVersions(Object.fromEntries(entries));
    });
    return () => {
      cancelled = true;
    };
  }, [pages, projectId]);

  // Wheel = zoom toward cursor (non-passive so we can preventDefault)
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const onWheel = (e) => {
      e.preventDefault();
      const rect = el.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;
      setView((v) => {
        const factor = Math.exp(-e.deltaY * 0.0015);
        const scale = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, v.scale * factor));
        const k = scale / v.scale;
        return { scale, x: mx - (mx - v.x) * k, y: my - (my - v.y) * k };
      });
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, []);

  const zoomAtCenter = useCallback((factor) => {
    const el = containerRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const mx = rect.width / 2;
    const my = rect.height / 2;
    setView((v) => {
      const scale = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, v.scale * factor));
      const k = scale / v.scale;
      return { scale, x: mx - (mx - v.x) * k, y: my - (my - v.y) * k };
    });
  }, []);

  const resetView = useCallback(() => setView({ x: 60, y: 40, scale: 1 }), []);

  // Drag empty space = pan
  const handlePanStart = (e) => {
    if (e.button !== 0) return;
    if (e.target !== containerRef.current && e.target.dataset.panLayer !== "true")
      return;
    e.preventDefault();
    const start = { mx: e.clientX, my: e.clientY, vx: view.x, vy: view.y };
    const onMove = (ev) => {
      setView((v) => ({
        ...v,
        x: start.vx + (ev.clientX - start.mx),
        y: start.vy + (ev.clientY - start.my),
      }));
    };
    const onUp = () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  };

  // Drag a node by its header to reposition; persist on drag-end
  const handleNodeDragStart = (e, page) => {
    if (e.button !== 0) return;
    e.preventDefault();
    e.stopPropagation();
    const pos = positions[page.slug];
    if (!pos) return;
    const start = { mx: e.clientX, my: e.clientY, x: pos.x, y: pos.y, moved: false };
    let latest = { x: pos.x, y: pos.y };
    const onMove = (ev) => {
      const dx = (ev.clientX - start.mx) / view.scale;
      const dy = (ev.clientY - start.my) / view.scale;
      if (Math.abs(ev.clientX - start.mx) + Math.abs(ev.clientY - start.my) > 4) {
        start.moved = true;
      }
      latest = { x: start.x + dx, y: start.y + dy };
      setPositions((prev) => ({ ...prev, [page.slug]: latest }));
    };
    const onUp = () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
      if (!start.moved) return;
      suppressClickRef.current = true;
      setTimeout(() => {
        suppressClickRef.current = false;
      }, 0);
      projectsApi
        .updatePage(projectId, page.slug, {
          canvas_x: Math.round(latest.x * 100) / 100,
          canvas_y: Math.round(latest.y * 100) / 100,
        })
        .catch(() => {
          // Roll back to the pre-drag position on failure
          setPositions((prev) => ({
            ...prev,
            [page.slug]: { x: start.x, y: start.y },
          }));
        });
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  };

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
      const page = await createPage({ title: newTitle.trim(), slug });
      // Drop the new node at the current canvas center
      const el = containerRef.current;
      if (el && page) {
        const rect = el.getBoundingClientRect();
        const cx = Math.round((rect.width / 2 - view.x) / view.scale - NODE_W / 2);
        const cy = Math.round((rect.height / 2 - view.y) / view.scale - NODE_H / 2);
        setPositions((prev) => ({ ...prev, [page.slug]: { x: cx, y: cy } }));
        try {
          await projectsApi.updatePage(projectId, page.slug, {
            canvas_x: cx,
            canvas_y: cy,
          });
          await refresh();
        } catch {}
      }
      setShowCreate(false);
      setNewTitle("");
      setNewSlug("");
    } catch {}
    setCreating(false);
  };

  const ungenerated = pages.filter((p) => !versions[p.slug]);

  const handleGenerateAll = async () => {
    if (gen.active || !ungenerated.length) return;
    setGen({ active: true, done: 0, total: ungenerated.length, current: null });
    for (const page of ungenerated) {
      setGen((g) => ({ ...g, current: page.slug }));
      try {
        await startGeneration(projectId, page.slug, {
          prompt: page.prompt || "",
        });
      } catch {}
      setGen((g) => ({ ...g, done: g.done + 1 }));
    }
    setGen({ active: false, done: 0, total: 0, current: null });
    await refresh();
  };

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <Spinner size={32} />
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      {/* Header */}
      <div className="h-12 border-b border-slate-800 bg-slate-950/80 backdrop-blur-md flex items-center justify-between px-8 z-20 shrink-0">
        <div className="flex items-center gap-2 text-sm">
          <Link
            to={`/project/${projectId}`}
            className="text-slate-500 hover:text-white transition-colors"
          >
            {project?.name || "..."}
          </Link>
          <CaretRight className="text-slate-600" size={12} />
          <span className="text-white font-medium">Canvas</span>
        </div>
        <div className="flex items-center gap-2">
          {ungenerated.length > 0 && (
            <button
              onClick={handleGenerateAll}
              disabled={gen.active}
              className="flex items-center gap-2 bg-slate-800 hover:bg-slate-700 text-white px-3 py-1.5 rounded-lg text-sm font-medium transition-colors border border-slate-700 disabled:opacity-50"
            >
              {gen.active ? (
                <SpinnerGap className="animate-spin" size={14} />
              ) : (
                <MagicWand size={14} />
              )}
              {gen.active
                ? `Starting ${gen.done + 1}/${gen.total}${gen.current ? `: /${gen.current}` : ""}`
                : `Generate all (${ungenerated.length})`}
            </button>
          )}
          <button
            onClick={() => setShowCreate(true)}
            className="flex items-center gap-2 bg-brand-600 hover:bg-brand-500 text-white px-3 py-1.5 rounded-lg text-sm font-medium transition-colors shadow-lg shadow-brand-500/20"
          >
            <Plus size={14} />
            New Page
          </button>
          <Link
            to={`/project/${projectId}`}
            className="flex items-center gap-2 text-slate-400 hover:text-white transition-colors px-3 py-1.5 text-sm font-medium"
          >
            <Kanban size={14} />
            Grid view
          </Link>
        </div>
      </div>

      {/* Canvas surface */}
      <div
        ref={containerRef}
        onMouseDown={handlePanStart}
        className="flex-1 relative overflow-hidden bg-slate-950 cursor-grab active:cursor-grabbing select-none"
        style={{
          backgroundImage:
            "radial-gradient(circle, rgba(148,163,184,0.12) 1px, transparent 1px)",
          backgroundSize: `${24 * view.scale}px ${24 * view.scale}px`,
          backgroundPosition: `${view.x}px ${view.y}px`,
        }}
      >
        {/* World layer */}
        <div
          data-pan-layer="true"
          className="absolute top-0 left-0"
          style={{
            transform: `translate(${view.x}px, ${view.y}px) scale(${view.scale})`,
            transformOrigin: "0 0",
            width: 0,
            height: 0,
          }}
        >
          {pages.map((page) => {
            const pos = positions[page.slug] || defaultPosition(0);
            const version = versions[page.slug];
            return (
              <div
                key={page.id}
                className="absolute bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-xl hover:border-slate-600 transition-colors"
                style={{ left: pos.x, top: pos.y, width: NODE_W }}
              >
                {/* Drag handle header */}
                <div
                  onMouseDown={(e) => handleNodeDragStart(e, page)}
                  className="flex items-center justify-between gap-2 px-3 py-2 border-b border-slate-800 cursor-grab active:cursor-grabbing bg-slate-900"
                >
                  <div className="min-w-0">
                    <h3 className="text-white text-sm font-medium truncate">
                      {page.title}
                    </h3>
                    <p className="text-[11px] text-slate-500 font-mono truncate">
                      /{page.slug}
                    </p>
                  </div>
                  <Badge status={version ? "live" : "draft"}>
                    {version ? `v${version}` : "draft"}
                  </Badge>
                </div>

                {/* Live scaled preview — click opens the builder */}
                <div
                  onClick={() => {
                    if (suppressClickRef.current) return;
                    navigate(`/project/${projectId}/page/${page.slug}`);
                  }}
                  className="relative cursor-pointer"
                  style={{ width: NODE_W, height: PREVIEW_H }}
                >
                  {version ? (
                    <div className="absolute inset-0 overflow-hidden bg-white">
                      <div
                        style={{
                          width: VIRTUAL_W,
                          height: VIRTUAL_H,
                          transform: `scale(${PREVIEW_SCALE})`,
                          transformOrigin: "0 0",
                        }}
                      >
                        <iframe
                          src={getPreviewUrl(projectId, page.slug, version)}
                          title={`Preview of ${page.title}`}
                          className="w-full h-full border-none bg-white"
                          sandbox="allow-scripts"
                          loading="lazy"
                          tabIndex={-1}
                          style={{ pointerEvents: "none" }}
                        />
                      </div>
                    </div>
                  ) : (
                    <div className="absolute inset-0 bg-slate-950 flex flex-col items-center justify-center gap-2 text-slate-500">
                      <FileDashed size={24} />
                      <span className="text-xs">Not generated yet</span>
                    </div>
                  )}
                  {/* Hover overlay */}
                  <div className="absolute inset-0 bg-black/40 flex items-center justify-center opacity-0 hover:opacity-100 transition-all">
                    <span className="bg-white text-slate-900 px-3 py-1.5 rounded-full text-xs font-bold shadow-lg">
                      Open Builder
                    </span>
                  </div>
                </div>
              </div>
            );
          })}
        </div>

        {/* Zoom controls */}
        <div className="absolute bottom-6 left-1/2 -translate-x-1/2 flex gap-2 z-20">
          <div className="bg-slate-900 border border-slate-800 rounded-full px-4 py-2 flex items-center gap-4 text-xs font-mono shadow-xl text-slate-400">
            <button
              onClick={() => zoomAtCenter(1 / 1.25)}
              className="hover:text-white"
              title="Zoom out"
            >
              <Minus size={12} />
            </button>
            <span className="w-10 text-center">
              {Math.round(view.scale * 100)}%
            </span>
            <button
              onClick={() => zoomAtCenter(1.25)}
              className="hover:text-white"
              title="Zoom in"
            >
              <Plus size={12} />
            </button>
          </div>
          <button
            onClick={resetView}
            className="bg-slate-900 border border-slate-800 rounded-full w-9 h-9 flex items-center justify-center hover:bg-slate-800 text-slate-400 hover:text-white transition-colors shadow-xl"
            title="Reset view"
          >
            <ArrowsOutSimple size={16} />
          </button>
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
    </div>
  );
}

import { useState, useEffect, useRef, useCallback } from "react";
import { useParams } from "react-router-dom";
import useProject from "../hooks/useProject";
import useVersions from "../hooks/useVersions";
import useGeneration from "../hooks/useGeneration";
import { useApp } from "../context/AppContext";
import { getPreviewUrl, getAppPreviewUrl, uploadAsset } from "../api/assets";
import { API_BASE } from "../api/client";
import { getPage, createPage, listMessages, createMessage } from "../api/projects";
import { streamChat } from "../api/chat";
import PageBuilderHeader from "../components/layout/PageBuilderHeader";
import ChatSidebar from "../components/builder/ChatSidebar";
import DiscoveryForm from "../components/builder/DiscoveryForm";
import DirectionPicker from "../components/builder/DirectionPicker";
import PreviewFrame from "../components/builder/PreviewFrame";
import CodeView from "../components/builder/CodeView";
import ZoomControls from "../components/builder/ZoomControls";
import RightRail from "../components/builder/RightRail";
import SaveComponentModal from "../components/builder/SaveComponentModal";
import useVisualEdit from "../hooks/useVisualEdit";
import { render as renderBlock, rerender as rerenderBlock } from "../api/blocks";
import { listComponents, renderComponent } from "../api/components";
import { PencilSimple, Sparkle } from "@phosphor-icons/react";

export default function PageBuilderPage() {
  const { projectId, slug } = useParams();
  const { project, pages, refresh: refreshProject } = useProject(projectId);
  const { versions, refresh: refreshVersions } = useVersions(projectId, slug);
  const { models } = useApp();
  const gen = useGeneration(projectId);

  const [messages, setMessages] = useState([]);
  const [pageReady, setPageReady] = useState(false);
  const [device, setDevice] = useState(null);
  const [deviceFrame, setDeviceFrame] = useState(null);
  const [zoom, setZoom] = useState(100);
  const [activeVersion, setActiveVersion] = useState(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [viewMode, setViewMode] = useState("preview");
  const [editMode, setEditMode] = useState(false);
  const [saveComponentOpen, setSaveComponentOpen] = useState(false);
  const [projectComponents, setProjectComponents] = useState([]);
  const [forceDiscovery, setForceDiscovery] = useState(false); // "Create new design" trigger

  // Fetch project component library on mount + when projectId changes.
  useEffect(() => {
    if (!projectId) return;
    listComponents(projectId).then(setProjectComponents).catch(() => setProjectComponents([]));
  }, [projectId]);

  const refreshComponents = useCallback(() => {
    if (!projectId) return;
    listComponents(projectId).then(setProjectComponents).catch(() => {});
  }, [projectId]);
  const visualEdit = useVisualEdit({
    projectId,
    slug,
    version: activeVersion,
    enabled: editMode && viewMode === "preview",
  });
  const [pendingBrief, setPendingBrief] = useState(null); // { text, image } awaiting discovery answers
  const [pendingDirection, setPendingDirection] = useState(null); // { text, image, brief } awaiting direction pick
  const prevGenerating = useRef(false);

  const page = pages.find((p) => p.slug === slug);

  // Ensure the page exists in the DB before loading messages
  useEffect(() => {
    if (!projectId || !slug) return;
    let cancelled = false;
    getPage(projectId, slug)
      .catch(() =>
        createPage(projectId, { slug, title: slug.charAt(0).toUpperCase() + slug.slice(1) })
      )
      .then(() => { if (!cancelled) setPageReady(true); })
      .catch(() => { if (!cancelled) setPageReady(true); });
    return () => { cancelled = true; };
  }, [projectId, slug]);

  // Load persisted messages on mount (after page exists)
  useEffect(() => {
    if (!projectId || !slug || !pageReady) return;
    listMessages(projectId, slug)
      .then((saved) => {
        const restored = saved.map((m) => {
          const msg = { role: m.role, content: m.content, time: m.created_at };
          if (m.image) msg.image = m.image;
          if (m.meta && Object.keys(m.meta).length > 0) {
            if (m.meta.agents) msg.agents = m.meta.agents;
            if (m.meta.builds) msg.builds = m.meta.builds;
            if (m.meta.done !== undefined) msg.done = m.meta.done;
          }
          return msg;
        });
        setMessages(restored);
      })
      .catch(() => {});
  }, [projectId, slug, pageReady]);

  // Keep version selector in sync
  useEffect(() => {
    if (versions.length && !activeVersion) {
      setActiveVersion(versions[versions.length - 1].version_number);
    }
  }, [versions, activeVersion]);

  // Wire generation to version refresh
  useEffect(() => {
    gen.onVersionRefresh(refreshVersions);
  }, [gen, refreshVersions]);

  // Wire generation to project refresh (brand data auto-updates after generation)
  useEffect(() => {
    gen.onProjectRefresh(refreshProject);
  }, [gen, refreshProject]);

  // Detect generation completion: refresh preview and auto-select new version
  useEffect(() => {
    if (prevGenerating.current && !gen.generating) {
      setRefreshKey((k) => k + 1);
      setTimeout(() => {
        setActiveVersion(null);
      }, 500);
    }
    prevGenerating.current = gen.generating;
  }, [gen.generating]);

  // Project mode — the preview is the built workspace served at /preview/{id}/app/.
  // preview_ready WS events carry the URL + build hash (cache-buster) of the
  // latest successful build; before the first one, fall back to the app root.
  const isProjectMode = project?.mode === "project";
  const previewUrl = isProjectMode
    ? gen.previewReady
      ? `${API_BASE}${gen.previewReady.url}?b=${encodeURIComponent(gen.previewReady.buildHash || refreshKey)}`
      : getAppPreviewUrl(projectId) + `?b=${refreshKey}`
    : activeVersion
      ? getPreviewUrl(projectId, slug, activeVersion) + `?t=${refreshKey}`
      : getPreviewUrl(projectId, slug);

  // Live srcdoc streaming still applies while generating, but once a built
  // preview is ready (project mode) the URL preview wins.
  const liveHtml = isProjectMode && gen.previewReady ? null : gen.livePreview?.[slug]?.html;

  const isFirstBrief = (versions?.length || 0) === 0 && messages.every((m) => m.role !== "user");

  const startBuild = async ({ text, image, brief, directionId }) => {
    let imageUrl = null;
    if (image) {
      try {
        const result = await uploadAsset(projectId, image);
        imageUrl = result.url;
      } catch {}
    }

    const userMsg = {
      role: "user",
      content: text,
      image: imageUrl,
      time: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    };
    setMessages((prev) => [...prev, userMsg]);

    createMessage(projectId, slug, {
      role: "user",
      content: text,
      image: imageUrl,
    }).catch(() => {});

    const model =
      project?.model ||
      (models.models.length ? models.models[0].id : "openai/gpt-4o");

    const payload = { prompt: text, model };
    if (brief) payload.discovery_brief = brief;
    if (directionId) payload.direction_id = directionId;
    gen.start(slug, payload);
  };

  const handleChat = async ({ text }) => {
    const userMsg = {
      role: "user",
      content: text,
      time: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    };
    setMessages((prev) => [...prev, userMsg]);
    // Backend chat endpoint persists the user message — no createMessage call here.

    const liveId = `chat-${Date.now()}`;
    setMessages((prev) => [
      ...prev,
      { role: "agent", content: "", _liveId: liveId },
    ]);

    const editContext =
      editMode && viewMode === "preview"
        ? {
            mode: true,
            version: activeVersion,
            selection: visualEdit.selection || null,
            selections: visualEdit.selections && visualEdit.selections.length > 0
              ? visualEdit.selections
              : undefined,
          }
        : null;

    let agentText = "";
    streamChat(projectId, slug, text, {
      editContext,
      onEvent: (event) => {
        if (event.type === "text") {
          agentText += event.content;
          setMessages((prev) =>
            prev.map((m) => (m._liveId === liveId ? { ...m, content: agentText } : m))
          );
        } else if (event.type === "tool_call" && event.name === "start_build") {
          // Agent is about to fire the pipeline — open the WS so progress events arrive.
          gen.prepareBuildStream();
        } else if (event.type === "tool_use_stop" && event.name === "patch") {
          // Edit-mode agent emitted a Patch. Route it through the same
          // hook the inspector uses — same apply→srcDoc→PUT pipeline.
          if (event.input && typeof event.input === "object") {
            visualEdit.applyPatch(event.input);
          }
        } else if (event.type === "done") {
          setMessages((prev) =>
            prev.map((m) => (m._liveId === liveId ? { role: "agent", content: agentText } : m))
          );
        } else if (event.type === "error") {
          setMessages((prev) =>
            prev.map((m) =>
              m._liveId === liveId ? { role: "agent", content: `Error: ${event.message}` } : m
            )
          );
        }
      },
      onError: (err) => {
        setMessages((prev) =>
          prev.map((m) =>
            m._liveId === liveId ? { role: "agent", content: `Connection error: ${err.message}` } : m
          )
        );
      },
    });
  };

  const handleSend = async ({ text, image }) => {
    if (isFirstBrief) {
      // Defer until discovery form is answered (or skipped).
      setPendingBrief({ text, image });
      return;
    }
    if (image) {
      // Image uploads bypass the chat agent and trigger a build directly.
      await startBuild({ text, image });
      return;
    }
    await handleChat({ text });
  };

  const handleDiscoverySubmit = async (answers) => {
    // pending is either the message that triggered the survey, or — when
    // the user clicked "Create new design" — null, in which case the brief
    // IS the message.
    const pending = pendingBrief ?? { text: "", image: null };
    setPendingBrief(null);
    setForceDiscovery(false);
    const wantsDirection =
      (answers?.brand || answers?.brand_mode || "pick_direction") === "pick_direction" &&
      !answers?.direction_id;
    if (wantsDirection) {
      setPendingDirection({ ...pending, brief: answers });
      return;
    }
    await startBuild({ ...pending, brief: answers });
  };

  const handleDiscoverySkip = async () => {
    const pending = pendingBrief;
    setPendingBrief(null);
    setForceDiscovery(false);
    if (!pending) return; // "Create new design" with no answers → just close
    await startBuild(pending);
  };

  const handleCreateNewDesign = () => {
    // Force the discovery form open with a fresh slate, regardless of
    // whether versions exist or messages are present.
    setPendingDirection(null);
    setPendingBrief(null);
    setForceDiscovery(true);
  };

  const handleDirectionPick = async (directionId) => {
    const pending = pendingDirection;
    setPendingDirection(null);
    if (!pending) return;
    await startBuild({ ...pending, directionId });
  };

  const handleDirectionSkip = async () => {
    const pending = pendingDirection;
    setPendingDirection(null);
    if (!pending) return;
    await startBuild(pending);
  };

  const getAgentLabel = useCallback((name) => {
    const labels = {
      pm: "PM",
      designer: "Designer",
      developer: "Developer",
      reviewer: "Reviewer",
      markup: "Markup",
      style: "Style",
      style_scss: "SCSS",
      script: "Script",
      image: "Image",
    };
    return labels[name] || name.charAt(0).toUpperCase() + name.slice(1);
  }, []);

  // Maintain a single agent-progress message that updates as events arrive
  useEffect(() => {
    if (!gen.generating && Object.keys(gen.agents).length === 0) return;

    const agentEntries = Object.entries(gen.agents);
    if (agentEntries.length === 0 && !gen.pipelineAgents && gen.buildEvents.length === 0) return;

    const CANONICAL_ORDER = ["pm", "designer", "image", "developer", "markup", "style", "style_scss", "script", "reviewer"];
    const pipelineSet = gen.pipelineAgents || agentEntries.map(([name]) => name);
    const knownAgents = CANONICAL_ORDER.filter((k) => pipelineSet.includes(k));
    const agentsList = knownAgents.map((name) => {
      const agentData = gen.agents[name] || {};
      return {
        name,
        label: getAgentLabel(name),
        status: agentData.status || "pending",
        startedAt: agentData.startedAt || null,
        duration_s: agentData.duration_s ?? null,
        input_tokens: agentData.input_tokens || 0,
        output_tokens: agentData.output_tokens || 0,
        output_preview: agentData.output_preview || "",
        full_output: agentData.full_output || "",
        tool_calls_count: agentData.tool_calls_count || 0,
        model: agentData.model || "",
        reasoning: agentData.reasoning || "",
        thinking: agentData.thinking || "",
        steps: agentData.steps || [],
        iteration: agentData.iteration || 0,
        retryReason: agentData.retryReason || "",
      };
    });

    const done = !gen.generating;

    setMessages((prev) => {
      const idx = prev.findIndex((m) => m.role === "agent-progress" && m._genActive);
      const progressMsg = {
        role: "agent-progress",
        agents: agentsList,
        builds: gen.buildEvents,
        done,
        _genActive: !done,
      };

      if (idx >= 0) {
        const updated = [...prev];
        updated[idx] = progressMsg;
        return updated;
      }
      return [...prev, progressMsg];
    });

    if (done) {
      createMessage(projectId, slug, {
        role: "agent-progress",
        content: "",
        meta: { agents: agentsList, builds: gen.buildEvents, done: true },
      }).catch(() => {});
    }
  }, [gen.agents, gen.generating, gen.pipelineAgents, gen.buildEvents, getAgentLabel, projectId, slug]);

  // Add error message
  useEffect(() => {
    if (gen.error) {
      const errorContent = `Error: ${gen.error}`;
      setMessages((prev) => [
        ...prev,
        { role: "agent", content: errorContent },
      ]);
      createMessage(projectId, slug, {
        role: "agent",
        content: errorContent,
      }).catch(() => {});
    }
  }, [gen.error, projectId, slug]);

  return (
    <div className="h-screen flex flex-col overflow-hidden bg-slate-950 text-slate-300 font-sans antialiased selection:bg-brand-500 selection:text-white">
      <PageBuilderHeader
        projectId={projectId}
        page={page}
        device={device}
        onDeviceChange={(width, frame) => {
          setDevice(width);
          setDeviceFrame(frame || null);
        }}
        versions={versions}
        activeVersion={activeVersion}
        onVersionChange={setActiveVersion}
        viewMode={viewMode}
        onViewModeChange={setViewMode}
      />

      <div className="flex-1 flex overflow-hidden">
        <ChatSidebar
          messages={messages}
          onSend={handleSend}
          generating={gen.generating}
          editMode={editMode && viewMode === "preview"}
          editSelection={visualEdit.selection}
          editSelections={visualEdit.selections}
          onCreateNewDesign={handleCreateNewDesign}
          discoveryForm={
            pendingBrief || forceDiscovery ? (
              <DiscoveryForm
                initialPrompt={pendingBrief?.text || ""}
                onSubmit={handleDiscoverySubmit}
                onSkip={handleDiscoverySkip}
              />
            ) : pendingDirection ? (
              <DirectionPicker
                onPick={handleDirectionPick}
                onSkip={handleDirectionSkip}
              />
            ) : null
          }
        />

        <main className="flex-1 bg-[#0c0e14] relative flex flex-col items-center justify-center p-8 overflow-hidden">
          {/* Grid background */}
          <div
            className="absolute inset-0 z-0 opacity-20"
            style={{
              backgroundImage: "radial-gradient(#334155 1px, transparent 1px)",
              backgroundSize: "24px 24px",
            }}
          />

          {/* Dimensions label */}
          <div className="absolute top-4 text-xs font-mono text-slate-500 bg-slate-900/80 px-2 py-1 rounded border border-slate-800 z-20">
            {device || "100%"} <span className="text-slate-600">x</span> auto
          </div>

          {/* Preview or Code view */}
          <div
            className="relative flex items-center justify-center w-full h-full z-10"
            style={{ zoom: `${zoom}%` }}
          >
            {viewMode === "code" ? (
              <CodeView
                projectId={projectId}
                slug={slug}
                version={activeVersion}
                width={device}
              />
            ) : (
              <PreviewFrame
                src={previewUrl}
                html={liveHtml}
                contentHash={liveHtml ? gen.livePreview?.[slug]?.contentHash : null}
                editSrcDoc={editMode ? visualEdit.srcDoc : null}
                width={device}
                frame={deviceFrame}
              />
            )}
          </div>

          {/* Edit-mode toggle (only when a version has been generated). Blocks
              now live in the right-rail tab, no separate insert button needed. */}
          {viewMode === "preview" && activeVersion && (
            <button
              onClick={() => setEditMode((v) => !v)}
              className={`absolute top-4 right-4 z-20 inline-flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-semibold transition-colors border ${
                editMode
                  ? "bg-brand-500 border-brand-400 text-white"
                  : "bg-slate-900/80 border-slate-800 text-slate-300 hover:text-white"
              }`}
              title={editMode ? "Exit edit mode" : "Visual edit (htmlstudio)"}
            >
              <PencilSimple size={12} weight={editMode ? "fill" : "regular"} />
              {editMode ? "Editing" : "Edit"}
            </button>
          )}

          <ZoomControls zoom={zoom} onZoomChange={setZoom} />
        </main>

        {editMode && viewMode === "preview" && (
          <RightRail
            selection={visualEdit.selection}
            selections={visualEdit.selections}
            onApply={visualEdit.applyPatch}
            onApplyMany={visualEdit.applyPatches}
            onRerenderBlock={({ blockId, instanceId, targetId, config }) => {
              const html = rerenderBlock(blockId, config, instanceId);
              visualEdit.applyPatch({ kind: "set-outer-html", id: targetId, html });
            }}
            onSaveAsComponent={() => setSaveComponentOpen(true)}
            onClearSelection={visualEdit.clearSelection}
            saveState={visualEdit.saveState}
            projectComponents={projectComponents}
            onInsertBlock={async (def) => {
              if (!visualEdit.selection) {
                window.alert(
                  "Select an element in the preview first — clicks insert by replacing it.",
                );
                return;
              }
              let html;
              if (def.id?.startsWith("pc_")) {
                const r = await renderComponent(projectId, def.id, {});
                html = r.html;
              } else {
                html = renderBlock(def.id, {});
              }
              visualEdit.applyPatch({
                kind: "set-outer-html",
                id: visualEdit.selection.id,
                html,
              });
            }}
          />
        )}
      </div>

      <SaveComponentModal
        open={saveComponentOpen}
        projectId={projectId}
        selection={visualEdit.selection}
        getOuterHtml={visualEdit.getOuterHtml}
        pageSlug={slug}
        version={activeVersion}
        onClose={() => setSaveComponentOpen(false)}
        onSaved={() => {
          setSaveComponentOpen(false);
          refreshComponents();
        }}
      />
    </div>
  );
}

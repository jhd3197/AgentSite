import { useState, useCallback, useRef, useEffect } from "react";
import { startGeneration } from "../api/generate";
import useWebSocket from "./useWebSocket";

export default function useGeneration(projectId) {
  const [generating, setGenerating] = useState(false);
  const [agents, setAgents] = useState({});
  const [files, setFiles] = useState([]);
  const [generatedAssets, setGeneratedAssets] = useState([]);
  const [error, setError] = useState(null);
  const [pipelineAgents, setPipelineAgents] = useState(null);
  const [agentMeta, setAgentMeta] = useState(null);
  const [parallelGroups, setParallelGroups] = useState(null);
  // Phase 6 — live srcdoc preview per page slug
  const [livePreview, setLivePreview] = useState({}); // slug -> { html, contentHash }
  // Phase 7 — live todo list streamed from the deep-agent developer (if enabled)
  const [todos, setTodos] = useState([]);
  // Project mode — built workspace preview + build/checkpoint status feed
  const [previewReady, setPreviewReady] = useState(null); // { url, buildHash }
  const [buildEvents, setBuildEvents] = useState([]); // { kind: "build"|"checkpoint", ... }
  const ws = useWebSocket(projectId);
  const versionRefreshRef = useRef(null);
  const projectRefreshRef = useRef(null);

  useEffect(() => {
    const unsubs = [
      ws.on("agent_start", (msg) => {
        setAgents((prev) => ({
          ...prev,
          [msg.agent]: { status: "running", startedAt: msg.data?.started_at, ...msg.data },
        }));
      }),
      ws.on("agent_complete", (msg) => {
        setAgents((prev) => ({
          ...prev,
          [msg.agent]: {
            ...prev[msg.agent],
            status: "complete",
            duration_s: msg.data?.duration_s,
            input_tokens: msg.data?.input_tokens,
            output_tokens: msg.data?.output_tokens,
            cost: msg.data?.cost || 0,
            output_preview: msg.data?.output_preview || "",
            full_output: msg.data?.full_output || "",
            tool_calls_count: msg.data?.tool_calls_count || 0,
            reasoning: msg.data?.reasoning || "",
          },
        }));
      }),
      // Non-fatal agent error — the pipeline may retry with a fallback.
      // Mark the agent as retrying without disconnecting the WebSocket.
      ws.on("agent_error", (msg) => {
        setAgents((prev) => ({
          ...prev,
          [msg.agent]: {
            ...prev[msg.agent],
            status: "retrying",
            error: msg.data?.message,
            retryReason: msg.data?.message || "Unknown error",
          },
        }));
      }),
      ws.on("agent_thinking", (msg) => {
        setAgents((prev) => ({
          ...prev,
          [msg.agent]: {
            ...prev[msg.agent],
            thinking: msg.data?.text || "",
          },
        }));
      }),
      ws.on("agent_step", (msg) => {
        setAgents((prev) => {
          const existing = prev[msg.agent] || {};
          const steps = [...(existing.steps || []), msg.data].slice(-10);
          return { ...prev, [msg.agent]: { ...existing, steps } };
        });
      }),
      ws.on("agent_iteration", (msg) => {
        setAgents((prev) => ({
          ...prev,
          [msg.agent]: {
            ...prev[msg.agent],
            iteration: msg.data?.iteration || 0,
          },
        }));
      }),
      ws.on("file_written", (msg) => {
        setFiles((prev) => [...prev, msg.data]);
      }),
      ws.on("todo_update", (msg) => {
        const list = msg.data?.todos;
        if (Array.isArray(list)) setTodos(list);
      }),
      ws.on("preview_update", (msg) => {
        const slug = msg.data?.page_slug;
        if (!slug) return;
        setLivePreview((prev) => ({
          ...prev,
          [slug]: {
            html: msg.data?.html || "",
            contentHash: msg.data?.content_hash || "",
            path: msg.data?.path || "",
          },
        }));
      }),
      ws.on("asset_created", (msg) => {
        setGeneratedAssets((prev) => [...prev, msg.data]);
      }),
      // Project mode — a successful build is being served; swap to URL preview.
      ws.on("preview_ready", (msg) => {
        if (!msg.data?.url) return;
        setPreviewReady({
          url: msg.data.url,
          buildHash: msg.data.build_hash || "",
        });
      }),
      // Project mode — build status lines for the progress feed.
      ws.on("build_started", (msg) => {
        setBuildEvents((prev) => [
          ...prev,
          { kind: "build", command: msg.data?.command || "build", status: "running" },
        ]);
      }),
      ws.on("build_finished", (msg) => {
        const finished = {
          status: msg.data?.ok ? "ok" : "failed",
          duration_s: msg.data?.duration_s ?? null,
          output_tail: msg.data?.output_tail || "",
        };
        setBuildEvents((prev) => {
          const next = [...prev];
          for (let i = next.length - 1; i >= 0; i--) {
            if (next[i].kind === "build" && next[i].status === "running") {
              next[i] = { ...next[i], ...finished };
              return next;
            }
          }
          // build_finished without a matching build_started — append standalone
          return [...next, { kind: "build", command: "build", ...finished }];
        });
      }),
      ws.on("checkpoint_created", (msg) => {
        setBuildEvents((prev) => [
          ...prev,
          {
            kind: "checkpoint",
            message: msg.data?.message || "Checkpoint created",
            ref: msg.data?.ref || "",
          },
        ]);
      }),
      ws.on("pipeline_plan", (msg) => {
        const agents = msg.data?.required_agents;
        if (agents && agents.length > 0) {
          setPipelineAgents(agents);
        }
        if (msg.data?.agent_meta) {
          setAgentMeta(msg.data.agent_meta);
        }
        if (msg.data?.parallel_groups) {
          setParallelGroups(msg.data.parallel_groups);
        }
      }),
      ws.on("generation_complete", (msg) => {
        setGenerating(false);
        // Phase 6 — once the final file is on disk, swap back to the static
        // preview URL so the iframe loads from the project filesystem.
        setLivePreview({});
        if (msg.data?.success === false && msg.data?.error) {
          setError(msg.data.error);
        } else {
          // Increment generation counter for support popup
          const count = parseInt(localStorage.getItem("agentsite_generation_count") || "0", 10) + 1;
          localStorage.setItem("agentsite_generation_count", String(count));
          window.dispatchEvent(new Event("agentsite_generation_complete"));
        }
        ws.disconnect();
        versionRefreshRef.current?.();
        projectRefreshRef.current?.();
      }),
      ws.on("error", (msg) => {
        setError((prev) => {
          // Avoid overwriting with a second error from the same failure
          if (prev) return prev;
          const detail = msg.data?.message || "Generation failed";
          const tb = msg.data?.traceback;
          return tb ? `${detail}\n\n${tb}` : detail;
        });
        setGenerating(false);
        ws.disconnect();
      }),
    ];
    return () => unsubs.forEach((fn) => fn());
  }, [ws]);

  // Reset state and open the WebSocket so pipeline events arrive.
  // Used by both direct gen.start() and the chat-driven flow (where the
  // chat agent's start_build tool kicks off generation on the backend).
  const prepareBuildStream = useCallback(() => {
    setGenerating(true);
    setAgents({});
    setFiles([]);
    setGeneratedAssets([]);
    setError(null);
    setPipelineAgents(null);
    setAgentMeta(null);
    setParallelGroups(null);
    setLivePreview({});
    setTodos([]);
    setPreviewReady(null);
    setBuildEvents([]);
    ws.connect();
  }, [ws]);

  const start = useCallback(
    async (slug, data) => {
      prepareBuildStream();
      try {
        await startGeneration(projectId, slug, data);
      } catch (err) {
        setError(err.message);
        setGenerating(false);
        ws.disconnect();
      }
    },
    [projectId, ws, prepareBuildStream]
  );

  const onVersionRefresh = useCallback((fn) => {
    versionRefreshRef.current = fn;
  }, []);

  const onProjectRefresh = useCallback((fn) => {
    projectRefreshRef.current = fn;
  }, []);

  const steer = useCallback((text) => {
    if (!text || !text.trim()) return;
    ws.send({ type: "steer", text: text.trim() });
  }, [ws]);

  return { generating, agents, files, generatedAssets, error, pipelineAgents, agentMeta, parallelGroups, livePreview, todos, previewReady, buildEvents, start, steer, prepareBuildStream, onVersionRefresh, onProjectRefresh };
}

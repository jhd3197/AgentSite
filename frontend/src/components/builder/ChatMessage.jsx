import { useState, useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import { WarningCircle, SpinnerGap, CheckCircle, CaretDown, CaretRight, Timer, Lightning, Terminal, Copy, ArrowsOut, X, Export, Brain, ArrowCounterClockwise, Wrench, GitCommit, Info } from "@phosphor-icons/react";
import { API_BASE } from "../../api/client";
import BloubAvatar from "../shared/BloubAvatar";

function formatDuration(seconds) {
  if (seconds < 60) return `${Math.round(seconds * 10) / 10}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return s > 0 ? `${m}m ${s}s` : `${m}m`;
}

function formatTokens(n) {
  if (n < 1000) return String(n);
  if (n < 1_000_000) return `${(n / 1000).toFixed(1).replace(/\.0$/, "")}k`;
  return `${(n / 1_000_000).toFixed(1).replace(/\.0$/, "")}M`;
}

function shortModelName(model) {
  if (!model) return null;
  const parts = model.split("/");
  return parts[parts.length - 1];
}

function ElapsedTimer({ since }) {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    if (!since) return;
    const start = new Date(since).getTime();
    const tick = () => setElapsed(Math.round((Date.now() - start) / 1000));
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [since]);
  return <span className="text-[10px] tabular-nums text-slate-500">{formatDuration(elapsed)}</span>;
}

function AgentRow({ agent: a }) {
  const [showOutput, setShowOutput] = useState(false);
  const [showFullModal, setShowFullModal] = useState(false);
  const [showReasoning, setShowReasoning] = useState(false);
  const [copied, setCopied] = useState(false);
  const hasOutput = a.status === "complete" && (a.output_preview || a.full_output);
  const hasReasoning = a.status === "complete" && !!a.reasoning;
  const fullText = a.full_output || a.output_preview || "";
  const hasMore = fullText.length > (a.output_preview || "").length;
  const isRunning = a.status === "running";
  const isRetrying = a.status === "retrying";
  const hasLiveThinking = isRunning && !!a.thinking;
  const hasLiveSteps = isRunning && a.steps && a.steps.length > 0;

  const handleCopy = async (e) => {
    e.stopPropagation();
    try {
      await navigator.clipboard.writeText(fullText);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {}
  };

  return (
    <div>
      <div className="flex items-center gap-2 text-xs">
        {a.status === "complete" && (
          <CheckCircle className="text-emerald-400 shrink-0" weight="fill" size={12} />
        )}
        {isRunning && (
          <SpinnerGap className="animate-spin text-brand-400 shrink-0" size={12} />
        )}
        {isRetrying && (
          <ArrowCounterClockwise className="animate-spin text-amber-400 shrink-0" size={12} />
        )}
        {a.status === "pending" && (
          <div className="w-3 h-3 rounded-full border border-slate-600 shrink-0" />
        )}
        <span className={`flex-1 ${a.status === "pending" ? "text-slate-500" : isRetrying ? "text-amber-300" : "text-slate-300"}`}>
          {a.label}
          {a.iteration > 0 && (
            <span className="ml-1 text-[10px] text-amber-500 font-medium">retry #{a.iteration}</span>
          )}
          {a.model && (
            <span className="ml-1.5 text-[10px] text-slate-600 font-normal" title={a.model}>{shortModelName(a.model)}</span>
          )}
        </span>
        {isRunning && a.startedAt && (
          <ElapsedTimer since={a.startedAt} />
        )}
        {a.status === "complete" && a.duration_s != null && (
          <span className="text-slate-500 tabular-nums">{formatDuration(a.duration_s)}</span>
        )}
        {a.status === "complete" && (a.input_tokens > 0 || a.output_tokens > 0) && (
          <span className="text-slate-600 tabular-nums" title={`${(a.input_tokens || 0).toLocaleString()} in / ${(a.output_tokens || 0).toLocaleString()} out`}>
            {formatTokens(a.input_tokens + a.output_tokens)} tok
          </span>
        )}
        {hasOutput && (
          <div className="flex items-center gap-1">
            <button
              onClick={() => setShowOutput((s) => !s)}
              className="text-slate-500 hover:text-slate-300 transition-colors cursor-pointer"
              title="Show agent output"
            >
              <Terminal size={12} />
            </button>
            <button
              onClick={handleCopy}
              className="text-slate-500 hover:text-slate-300 transition-colors cursor-pointer"
              title={copied ? "Copied!" : "Copy output"}
            >
              <Copy size={12} weight={copied ? "fill" : "regular"} />
            </button>
            {hasMore && (
              <button
                onClick={() => setShowFullModal(true)}
                className="text-slate-500 hover:text-slate-300 transition-colors cursor-pointer"
                title="View full output"
              >
                <ArrowsOut size={12} />
              </button>
            )}
          </div>
        )}
      </div>
      {/* Retry reason */}
      {isRetrying && a.retryReason && (
        <div className="mt-1.5 flex items-start gap-1.5 text-[11px] text-amber-400/80">
          <ArrowCounterClockwise size={11} className="shrink-0 mt-0.5" />
          <span className="line-clamp-2">{a.retryReason}</span>
        </div>
      )}
      {/* Live thinking */}
      {hasLiveThinking && (
        <div className="mt-1.5">
          <div className="flex items-center gap-1.5 text-[11px] text-indigo-400/70 mb-1">
            <Brain size={11} className="animate-pulse" />
            <span>Thinking...</span>
          </div>
          <pre className="text-[10px] text-indigo-300/50 whitespace-pre-wrap font-mono overflow-hidden max-h-20 bg-indigo-950/15 rounded-lg p-2 border border-indigo-500/10">
            {a.thinking.slice(-500)}
          </pre>
        </div>
      )}
      {/* Live steps */}
      {hasLiveSteps && (
        <div className="mt-1.5 space-y-0.5">
          {a.steps.slice(-3).map((step, i) => (
            <div key={i} className="flex items-center gap-1.5 text-[10px] text-slate-500">
              <Wrench size={10} className="shrink-0" />
              <span className="truncate">
                {step.tool_name ? `${step.tool_name}()` : step.step_type || "step"}
              </span>
            </div>
          ))}
        </div>
      )}
      {hasReasoning && (
        <button
          onClick={() => setShowReasoning((s) => !s)}
          className="flex items-center gap-1.5 mt-1.5 text-[11px] text-indigo-400/70 hover:text-indigo-300 transition-colors cursor-pointer"
        >
          <Brain size={12} />
          <span>Thinking</span>
          {showReasoning ? <CaretDown size={10} /> : <CaretRight size={10} />}
        </button>
      )}
      {showReasoning && hasReasoning && (
        <pre className="mt-1 mb-1 text-[11px] text-indigo-300/60 whitespace-pre-wrap font-mono overflow-x-auto max-h-48 overflow-y-auto bg-indigo-950/20 rounded-lg p-2.5 border border-indigo-500/10">
          {a.reasoning}
        </pre>
      )}
      {showOutput && (a.output_preview || a.full_output) && (
        <pre className="mt-1.5 mb-1 text-[11px] text-slate-400 whitespace-pre-wrap font-mono overflow-x-auto max-h-48 overflow-y-auto bg-slate-950 rounded-lg p-2.5 border border-slate-800">
          {a.output_preview || a.full_output}
        </pre>
      )}
      {showFullModal && createPortal(
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={() => setShowFullModal(false)}>
          <div className="bg-slate-900 border border-slate-700 rounded-xl shadow-2xl w-[90vw] max-w-3xl max-h-[80vh] flex flex-col" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800">
              <span className="text-sm font-medium text-slate-300">{a.label} — Full Output</span>
              <div className="flex items-center gap-2">
                <button onClick={handleCopy} className="text-slate-400 hover:text-slate-200 transition-colors cursor-pointer text-xs flex items-center gap-1">
                  <Copy size={14} weight={copied ? "fill" : "regular"} />
                  {copied ? "Copied" : "Copy"}
                </button>
                <button onClick={() => setShowFullModal(false)} className="text-slate-400 hover:text-slate-200 transition-colors cursor-pointer">
                  <X size={16} />
                </button>
              </div>
            </div>
            <pre className="flex-1 overflow-auto p-4 text-[11px] text-slate-400 whitespace-pre-wrap font-mono">
              {fullText}
            </pre>
          </div>
        </div>,
        document.body
      )}
    </div>
  );
}

function buildAgentLogs(agents) {
  const lines = [];
  lines.push(`=== AgentSite Pipeline Log ===`);
  lines.push(`Timestamp: ${new Date().toISOString()}`);
  lines.push("");

  for (const a of agents) {
    lines.push(`--- ${a.label} ${a.model ? `(${a.model})` : ""} ---`);
    lines.push(`Status: ${a.status}`);
    if (a.duration_s != null) lines.push(`Duration: ${formatDuration(a.duration_s)}`);
    if (a.input_tokens || a.output_tokens) {
      lines.push(`Tokens: ${(a.input_tokens || 0).toLocaleString()} in / ${(a.output_tokens || 0).toLocaleString()} out`);
    }
    if (a.tool_calls_count) lines.push(`Tool calls: ${a.tool_calls_count}`);
    if (a.error) lines.push(`Error: ${a.error}`);
    if (a.reasoning) {
      lines.push("");
      lines.push("Reasoning:");
      lines.push(a.reasoning);
    }
    const output = a.full_output || a.output_preview;
    if (output) {
      lines.push("");
      lines.push("Output:");
      lines.push(output);
    }
    lines.push("");
  }

  const totalDuration = agents.reduce((s, a) => s + (a.duration_s || 0), 0);
  const totalTokens = agents.reduce((s, a) => s + (a.input_tokens || 0) + (a.output_tokens || 0), 0);
  lines.push(`--- Totals ---`);
  lines.push(`Duration: ${formatDuration(totalDuration)}`);
  lines.push(`Tokens: ${totalTokens.toLocaleString()}`);

  return lines.join("\n");
}

// Verification report URLs are root-relative (/preview/...) — same base as assets.js helpers.
function screenshotUrl(u) {
  return u && !String(u).startsWith("http") ? `${API_BASE}${u}` : u;
}

function problemText(v) {
  if (typeof v === "string") return v;
  if (v && typeof v === "object") return v.message || v.text || v.url || JSON.stringify(v);
  return String(v);
}

// Flatten a verify_report's route results into displayable problem lines:
// console errors first, then failed requests, then missing pages.
function collectVerifyProblems(b) {
  const problems = [];
  for (const r of b.routes || []) {
    for (const e of r.console_errors || []) problems.push(`${r.route}: ${problemText(e)}`);
  }
  for (const r of b.routes || []) {
    for (const f of r.failed_requests || []) problems.push(`${r.route}: failed request — ${problemText(f)}`);
  }
  for (const p of b.missing_pages || []) problems.push(`missing page: ${p}`);
  return problems;
}

// Project mode — build / checkpoint / verify / triage / specialist status lines
// streamed during generation.
function BuildStatusLine({ event: b }) {
  if (b.kind === "verify") {
    if (b.status === "skipped") {
      return (
        <div className="flex items-center gap-1.5 text-[11px] text-slate-500">
          <Info size={11} className="shrink-0" />
          <span className="truncate">
            verification skipped{b.skip_reason ? ` — ${b.skip_reason}` : ""}
          </span>
        </div>
      );
    }
    const failed = b.status === "failed";
    const problems = failed ? collectVerifyProblems(b) : [];
    const shots = b.screenshot_urls || [];
    return (
      <div>
        <div className={`flex items-center gap-1.5 text-[11px] ${failed ? "text-red-400" : "text-slate-400"}`}>
          {b.status === "running" && (
            <SpinnerGap className="animate-spin text-brand-400 shrink-0" size={11} />
          )}
          {b.status === "ok" && (
            <CheckCircle className="text-emerald-400 shrink-0" weight="fill" size={11} />
          )}
          {failed && (
            <WarningCircle className="text-red-400 shrink-0" weight="fill" size={11} />
          )}
          {b.status === "running" && (
            <span className="truncate">
              Verifying {b.route_count || 0} route{(b.route_count || 0) === 1 ? "" : "s"}…
            </span>
          )}
          {b.status === "ok" && (
            <span className="truncate">{b.summary || "verification passed"}</span>
          )}
          {failed && <span className="truncate">verification failed — retrying</span>}
          {b.status !== "running" && b.duration_s != null && (
            <span className="ml-auto text-slate-500 tabular-nums shrink-0">
              {formatDuration(b.duration_s)}
            </span>
          )}
        </div>
        {failed && problems.length > 0 && (
          <pre className="mt-1 text-[10px] text-red-300/70 whitespace-pre-wrap font-mono max-h-24 overflow-y-auto bg-red-950/30 rounded-lg p-2 border border-red-500/10">
            {problems.slice(0, 3).join("\n")}
            {problems.length > 3 ? `\n+${problems.length - 3} more` : ""}
          </pre>
        )}
        {shots.length > 0 && (
          <div className="mt-1.5 flex items-center gap-1.5 overflow-x-auto">
            {shots.slice(0, 6).map((url, i) => (
              <a
                key={i}
                href={screenshotUrl(url)}
                target="_blank"
                rel="noreferrer"
                className="shrink-0"
                title={String(url).split("/").pop()}
              >
                <img
                  src={screenshotUrl(url)}
                  alt={String(url).split("/").pop() || "screenshot"}
                  loading="lazy"
                  className="h-16 w-24 rounded border border-slate-700 object-cover object-top hover:border-brand-400 transition-colors"
                />
              </a>
            ))}
            {shots.length > 6 && (
              <span className="shrink-0 text-[10px] text-slate-500 px-1">
                +{shots.length - 6}
              </span>
            )}
          </div>
        )}
      </div>
    );
  }
  if (b.kind === "checkpoint") {
    return (
      <div className="flex items-center gap-1.5 text-[11px] text-slate-500">
        <GitCommit size={11} className="shrink-0" />
        <span className="truncate">{b.message}</span>
        {b.ref && (
          <span className="font-mono text-slate-600 shrink-0">{String(b.ref).slice(0, 7)}</span>
        )}
      </div>
    );
  }
  if (b.kind === "triage") {
    const skipped = [!b.needs_pm && "PM", !b.needs_designer && "designer"].filter(Boolean);
    const label =
      b.bucket === "tweak"
        ? "Scoped build: quick tweak — developer only"
        : b.bucket === "partial"
          ? `Scoped build: partial update${skipped.length ? ` — skipping ${skipped.join(" & ")}` : ""}`
          : "Full rebuild planned";
    return (
      <div
        className="flex items-center gap-1.5 text-[11px] text-slate-500"
        title={b.reason || undefined}
      >
        <Info size={11} className="shrink-0" />
        <span className="truncate">{label}</span>
      </div>
    );
  }
  if (b.kind === "specialist") {
    const failed = b.status === "failed";
    return (
      <div>
        <div className={`flex items-center gap-1.5 text-[11px] ${failed ? "text-red-400" : "text-slate-400"}`}>
          {b.status === "running" && (
            <SpinnerGap className="animate-spin text-brand-400 shrink-0" size={11} />
          )}
          {b.status === "ok" && (
            <CheckCircle className="text-emerald-400 shrink-0" weight="fill" size={11} />
          )}
          {failed && (
            <WarningCircle className="text-red-400 shrink-0" weight="fill" size={11} />
          )}
          {b.status === "running" && (
            <span className="truncate">
              {b.specialist} working{b.task ? `: ${b.task}` : ""}…
            </span>
          )}
          {b.status === "ok" && <span className="truncate">{b.specialist} done</span>}
          {failed && <span className="truncate">{b.specialist} failed — continuing</span>}
          {b.status !== "running" && b.duration_s != null && (
            <span className="ml-auto text-slate-500 tabular-nums shrink-0">
              {formatDuration(b.duration_s)}
            </span>
          )}
        </div>
        {b.status !== "running" && b.summary && (
          <div className="mt-0.5 text-[10px] text-slate-500 truncate" title={b.summary}>
            {b.summary}
          </div>
        )}
      </div>
    );
  }
  const failed = b.status === "failed";
  return (
    <div>
      <div className={`flex items-center gap-1.5 text-[11px] ${failed ? "text-red-400" : "text-slate-400"}`}>
        {b.status === "running" && (
          <SpinnerGap className="animate-spin text-brand-400 shrink-0" size={11} />
        )}
        {b.status === "ok" && (
          <CheckCircle className="text-emerald-400 shrink-0" weight="fill" size={11} />
        )}
        {failed && (
          <WarningCircle className="text-red-400 shrink-0" weight="fill" size={11} />
        )}
        <span className="font-mono truncate">{b.command || "build"}</span>
        {b.status === "running" && <span className="text-slate-500 shrink-0">building…</span>}
        {failed && <span className="shrink-0">build failed — retrying</span>}
        {b.status !== "running" && b.duration_s != null && (
          <span className="ml-auto text-slate-500 tabular-nums shrink-0">
            {formatDuration(b.duration_s)}
          </span>
        )}
      </div>
      {failed && b.output_tail && (
        <pre className="mt-1 text-[10px] text-red-300/70 whitespace-pre-wrap font-mono max-h-24 overflow-y-auto bg-red-950/30 rounded-lg p-2 border border-red-500/10">
          {b.output_tail}
        </pre>
      )}
    </div>
  );
}

// Which bloub state the avatar plays for the current pipeline situation.
function pipelineMood(agents, builds) {
  if (agents.some((a) => a.status === "retrying")) return "alert";
  const lastBuild = builds[builds.length - 1];
  if (lastBuild?.status === "running") {
    if (lastBuild.kind === "verify") return "wide";
    if (lastBuild.kind === "specialist") return "play";
    return "orbit";
  }
  if (lastBuild?.status === "failed") return "alert";
  const current = agents.find((a) => a.status === "running");
  if (current) {
    const n = `${current.name || ""} ${current.label || ""}`.toLowerCase();
    if (n.includes("design")) return "swirl";
    if (n.includes("dev")) return "orbit";
    if (n.includes("review")) return "wide";
    return "thinking"; // PM, triage, anything plan-shaped
  }
  return "thinking";
}

function AgentProgressMessage({ message }) {
  const [expanded, setExpanded] = useState(false);
  const [logsCopied, setLogsCopied] = useState(false);
  const { agents = [], done, builds = [] } = message;

  // Celebrate only on the live transition to done — an old card remounting
  // from scrollback must not replay the burst.
  const [celebrating, setCelebrating] = useState(false);
  const prevDone = useRef(done);
  useEffect(() => {
    if (done && !prevDone.current) {
      setCelebrating(true);
      const id = setTimeout(() => setCelebrating(false), 1800);
      prevDone.current = done;
      return () => clearTimeout(id);
    }
    prevDone.current = done;
  }, [done]);

  const live = !done || celebrating;
  const mood = done ? (celebrating ? "burst" : "idle") : pipelineMood(agents, builds);

  const current = agents.find((a) => a.status === "running");
  const lastCompleted = [...agents].reverse().find((a) => a.status === "complete");
  const summary = done
    ? "All agents completed"
    : current
      ? `${current.label} working...`
      : lastCompleted
        ? `${lastCompleted.label} completed`
        : "Starting pipeline...";

  return (
    <div className="flex flex-col items-start gap-1">
      <div className="flex items-center gap-2 mb-1 ml-1">
        <BloubAvatar size={34} state={mood} animate={live} follow={live} className="-m-[6px]" />
        <span className="text-xs font-medium text-slate-400">AgentSite</span>
      </div>
      <div className="bg-slate-900 border border-slate-800 text-slate-300 px-4 py-3 rounded-2xl msg-agent max-w-[90%] shadow-sm w-full">
        <button
          onClick={() => setExpanded((e) => !e)}
          className="flex items-center gap-2 w-full text-left cursor-pointer"
        >
          {!done && <SpinnerGap className="animate-spin text-brand-400 shrink-0" size={14} />}
          {done && <CheckCircle className="text-emerald-400 shrink-0" weight="fill" size={14} />}
          <span className="text-sm flex-1">{summary}</span>
          {expanded ? (
            <CaretDown className="text-slate-500 shrink-0" size={12} />
          ) : (
            <CaretRight className="text-slate-500 shrink-0" size={12} />
          )}
        </button>
        {builds.length > 0 && (
          <div className="mt-2 space-y-1 border-t border-slate-800 pt-2">
            {builds.slice(-4).map((b, i) => (
              <BuildStatusLine key={i} event={b} />
            ))}
          </div>
        )}
        {expanded && (
          <div className="mt-3 space-y-2 border-t border-slate-800 pt-3">
            {agents.map((a) => (
              <AgentRow key={a.name} agent={a} />
            ))}
            {done && agents.length > 0 && (
              <div className="flex items-center gap-2 text-xs border-t border-slate-800 pt-2 mt-2 text-slate-400">
                <Timer size={12} className="shrink-0" />
                <span>
                  {formatDuration(agents.reduce((s, a) => s + (a.duration_s || 0), 0))} total
                </span>
                <Lightning size={12} className="shrink-0 ml-2" />
                <span title={`${agents.reduce((s, a) => s + (a.input_tokens || 0) + (a.output_tokens || 0), 0).toLocaleString()} tokens`}>
                  {formatTokens(agents.reduce((s, a) => s + (a.input_tokens || 0) + (a.output_tokens || 0), 0))} tokens
                </span>
                <button
                  onClick={async () => {
                    try {
                      await navigator.clipboard.writeText(buildAgentLogs(agents));
                      setLogsCopied(true);
                      setTimeout(() => setLogsCopied(false), 1500);
                    } catch {}
                  }}
                  className="ml-auto flex items-center gap-1 text-slate-500 hover:text-slate-300 transition-colors cursor-pointer"
                  title="Copy full pipeline logs to clipboard"
                >
                  <Export size={12} />
                  <span>{logsCopied ? "Copied" : "Export Logs"}</span>
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export default function ChatMessage({ message }) {
  const isUser = message.role === "user";
  const isError = !isUser && message.content?.startsWith("Error:");

  if (message.role === "agent-progress") {
    return <AgentProgressMessage message={message} />;
  }

  if (isUser) {
    return (
      <div className="flex flex-col items-end gap-1">
        <div className="bg-brand-600 text-white px-4 py-3 rounded-2xl msg-user max-w-[90%] shadow-md">
          <p className="text-sm whitespace-pre-wrap">{message.content}</p>
          {message.image && (
            <img
              src={message.image}
              alt="Uploaded"
              className="mt-2 rounded-lg max-h-40 object-cover"
            />
          )}
        </div>
        {message.time && (
          <span className="text-[10px] text-slate-500 mr-1">
            {message.time}
          </span>
        )}
      </div>
    );
  }

  if (isError) {
    // Parse error: first line is summary, rest (if any) is traceback
    const errorText = message.content.replace(/^Error:\s*/, "");
    const lines = errorText.split("\n\n");
    const summary = lines[0];
    const traceback = lines.length > 1 ? lines.slice(1).join("\n\n") : null;

    return (
      <div className="flex flex-col items-start gap-1">
        <div className="flex items-center gap-2 mb-1 ml-1">
          <BloubAvatar
            size={30}
            state="exclaim"
            animate={false}
            frozenAt={1.2}
            gradient={["#ef4444", "#b91c1c"]}
            className="-m-[5px]"
          />
          <span className="text-xs font-medium text-red-400">Error</span>
        </div>
        <div className="bg-red-950/40 border border-red-500/20 text-red-300 px-4 py-3 rounded-2xl msg-agent max-w-[90%] shadow-sm">
          <p className="text-sm font-medium mb-1">{summary}</p>
          {traceback && (
            <details className="mt-2">
              <summary className="text-xs text-red-400/70 cursor-pointer hover:text-red-300 select-none">
                Show details
              </summary>
              <pre className="mt-2 text-[11px] text-red-300/60 whitespace-pre-wrap font-mono overflow-x-auto max-h-60 overflow-y-auto bg-red-950/30 rounded-lg p-3 border border-red-500/10">
                {traceback}
              </pre>
            </details>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col items-start gap-1">
      <div className="flex items-center gap-2 mb-1 ml-1">
        <BloubAvatar size={30} state="idle" animate={false} className="-m-[5px]" />
        <span className="text-xs font-medium text-slate-400">AgentSite</span>
      </div>
      <div className="bg-slate-900 border border-slate-800 text-slate-300 px-4 py-3 rounded-2xl msg-agent max-w-[90%] shadow-sm">
        <p className="text-sm whitespace-pre-wrap">{message.content}</p>
      </div>
    </div>
  );
}

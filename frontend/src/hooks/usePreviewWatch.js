import { useState, useEffect, useCallback, useRef } from "react";

const MAX_ISSUES = 80;

function issueKey(evt) {
  return `${evt.type}|${evt.selector || ""}|${evt.message || ""}`;
}

/**
 * Receives friction events relayed by the injected preview watcher
 * (see agentsite/engine/watch.py) via postMessage from the sandboxed
 * preview iframe. Aggregates duplicates and exposes a clean issue list.
 *
 * @param {string|number} resetKey change clears accumulated issues
 *   (pass the preview URL / build hash so a fresh build starts a fresh session).
 */
export default function usePreviewWatch(resetKey) {
  const [issues, setIssues] = useState([]);
  const seenRef = useRef(new Map()); // key -> index into issues

  useEffect(() => {
    setIssues([]);
    seenRef.current = new Map();
  }, [resetKey]);

  useEffect(() => {
    function onMessage(e) {
      const data = e.data;
      if (!data || typeof data !== "object" || !Array.isArray(data.__asWatch)) return;
      const batch = data.__asWatch.filter((evt) => evt && typeof evt === "object" && evt.type);
      if (!batch.length) return;
      setIssues((prev) => {
        const next = [...prev];
        for (const evt of batch) {
          const key = issueKey(evt);
          const idx = seenRef.current.get(key);
          if (idx !== undefined && next[idx]) {
            next[idx] = { ...next[idx], count: (next[idx].count || 1) + 1, lastAt: evt.t };
          } else {
            seenRef.current.set(key, next.length);
            next.push({ ...evt, count: 1, lastAt: evt.t });
          }
        }
        return next.slice(-MAX_ISSUES);
      });
    }
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, []);

  const clearIssues = useCallback(() => {
    setIssues([]);
    seenRef.current = new Map();
  }, []);

  return { issues, clearIssues };
}

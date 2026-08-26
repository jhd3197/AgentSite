import { useState, useRef } from "react";
import useLocalStorage from "../../../hooks/useLocalStorage";
import { DEPLOY_STAGES, DEFAULT_CFG } from "./constants";

export default function useDeployment({ projectId, pageCount }) {
  const [cfg, setCfg] = useLocalStorage(
    `agentsite:deploy:cfg:${projectId}`,
    DEFAULT_CFG
  );
  const [history, setHistory] = useLocalStorage(
    `agentsite:deploy:history:${projectId}`,
    []
  );
  const [envVars, setEnvVars] = useLocalStorage(
    `agentsite:deploy:env:${projectId}`,
    []
  );
  const [domains, setDomains] = useLocalStorage(
    `agentsite:deploy:domains:${projectId}`,
    []
  );

  const [newDomain, setNewDomain] = useState("");
  const [deploying, setDeploying] = useState(false);
  const [stage, setStage] = useState(null);
  const [stageTimes, setStageTimes] = useState({});
  const stageRef = useRef(null);

  const primaryDomain =
    domains.find((d) => d.primary && d.verified)?.host ||
    domains.find((d) => d.verified)?.host ||
    `${projectId}.agentsite.app`;

  const lastReady = history.find((h) => h.status === "ready");

  const runDeploy = async (env = "production") => {
    if (deploying) return;
    setDeploying(true);
    setStageTimes({});
    const id = Math.random().toString(36).slice(2, 10);
    const baseEntry = {
      id,
      env,
      status: "building",
      branch: cfg.branch,
      provider: cfg.provider || "agentsite",
      domain: primaryDomain,
      started_at: new Date().toISOString(),
      finished_at: null,
      duration_ms: null,
      commit: `gen-${Math.random().toString(16).slice(2, 8)}`,
      message: `Deploy ${pageCount} page${pageCount === 1 ? "" : "s"} to ${env}`,
    };
    setHistory((h) => [baseEntry, ...h]);

    const t0 = Date.now();
    for (const s of DEPLOY_STAGES.slice(0, -1)) {
      setStage(s.id);
      stageRef.current = s.id;
      const t = Date.now();
      await new Promise((r) => setTimeout(r, s.duration));
      setStageTimes((st) => ({ ...st, [s.id]: Date.now() - t }));
    }

    const duration = Date.now() - t0;
    setStage("live");
    setHistory((h) =>
      h.map((e) =>
        e.id === id
          ? {
              ...e,
              status: "ready",
              finished_at: new Date().toISOString(),
              duration_ms: duration,
            }
          : e
      )
    );
    setTimeout(() => {
      setDeploying(false);
      setStage(null);
    }, 800);
  };

  const addDomain = () => {
    const host = newDomain.trim().toLowerCase().replace(/^https?:\/\//, "");
    if (!host || domains.find((d) => d.host === host)) return;
    setDomains([...domains, { host, verified: false, primary: domains.length === 0 }]);
    setNewDomain("");
  };

  const removeDomain = (host) => setDomains(domains.filter((d) => d.host !== host));

  const verifyDomain = (host) =>
    setDomains(domains.map((d) => (d.host === host ? { ...d, verified: true } : d)));

  const setPrimary = (host) =>
    setDomains(domains.map((d) => ({ ...d, primary: d.host === host })));

  const addEnvVar = () => setEnvVars([...envVars, { key: "", value: "" }]);

  const updateEnvVar = (idx, updated) => {
    const next = [...envVars];
    next[idx] = updated;
    setEnvVars(next);
  };

  const removeEnvVar = (key) => setEnvVars(envVars.filter((e) => e.key !== key));

  return {
    cfg,
    setCfg,
    history,
    envVars,
    domains,
    newDomain,
    setNewDomain,
    deploying,
    stage,
    stageTimes,
    primaryDomain,
    lastReady,
    runDeploy,
    addDomain,
    removeDomain,
    verifyDomain,
    setPrimary,
    addEnvVar,
    updateEnvVar,
    removeEnvVar,
  };
}

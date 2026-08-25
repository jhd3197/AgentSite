import { fetchJSON } from "./client";

export async function getCatalog() {
  return fetchJSON("/api/agents/catalog");
}

export async function listAgents() {
  return fetchJSON("/api/agents");
}

export async function updateAgent(name, config) {
  return fetchJSON(`/api/agents/${name}`, {
    method: "PUT",
    body: JSON.stringify(config),
  });
}

export async function getAgentRuns(limit = 50, since = null) {
  const params = new URLSearchParams({ limit });
  if (since) params.set("since", since);
  return fetchJSON(`/api/agents/runs?${params}`);
}

export async function getAgentStats(since = null) {
  const params = since ? `?since=${encodeURIComponent(since)}` : "";
  return fetchJSON(`/api/agents/stats${params}`);
}

export async function getAgentDailyStats(days = 30) {
  return fetchJSON(`/api/agents/stats/daily?days=${days}`);
}

export async function getTodayStats() {
  return fetchJSON("/api/agents/stats/today");
}

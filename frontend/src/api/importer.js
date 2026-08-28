import { fetchJSON } from "./client";

export const importHtml = (projectId, data) =>
  fetchJSON(`/api/projects/${projectId}/import`, {
    method: "POST",
    body: JSON.stringify(data),
  });

export const importFromUrl = (projectId, data) =>
  fetchJSON(`/api/projects/${projectId}/import/url`, {
    method: "POST",
    body: JSON.stringify(data),
  });

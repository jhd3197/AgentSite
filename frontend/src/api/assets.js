import { fetchJSON, uploadFile, API_BASE } from "./client";

export const listAssets = (projectId) =>
  fetchJSON(`/api/projects/${projectId}/assets`);

export const uploadAsset = (projectId, file) =>
  uploadFile(`/api/projects/${projectId}/assets`, file);

export const deleteAsset = (projectId, filename) =>
  fetchJSON(`/api/projects/${projectId}/assets/${filename}`, { method: "DELETE" });

export const getAssetUrl = (projectId, filename) =>
  `${API_BASE}/preview/${projectId}/assets/${filename}`;

export const getPreviewUrl = (projectId, slug, version) => {
  if (version) {
    return `${API_BASE}/preview/${projectId}/${slug}/v/${version}/index.html`;
  }
  return `${API_BASE}/preview/${projectId}/${slug}`;
};

// Project mode — built/static workspace served at a single app root.
export const getAppPreviewUrl = (projectId) =>
  `${API_BASE}/preview/${projectId}/app/`;

export const getExportUrl = (projectId) =>
  `${API_BASE}/api/projects/${projectId}/export`;

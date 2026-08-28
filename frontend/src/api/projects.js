import { fetchJSON } from "./client";

export const listProjects = () => fetchJSON("/api/projects");

export const getProject = (id) => fetchJSON(`/api/projects/${id}`);

export const createProject = (data) =>
  fetchJSON("/api/projects", { method: "POST", body: JSON.stringify(data) });

export const updateProject = (id, data) =>
  fetchJSON(`/api/projects/${id}`, { method: "PUT", body: JSON.stringify(data) });

export const deleteProject = (id) =>
  fetchJSON(`/api/projects/${id}`, { method: "DELETE" });

export const listPages = (projectId) =>
  fetchJSON(`/api/projects/${projectId}/pages`);

export const createPage = (projectId, data) =>
  fetchJSON(`/api/projects/${projectId}/pages`, {
    method: "POST",
    body: JSON.stringify(data),
  });

export const getPage = (projectId, slug) =>
  fetchJSON(`/api/projects/${projectId}/pages/${slug}`);

export const updatePage = (projectId, slug, data) =>
  fetchJSON(`/api/projects/${projectId}/pages/${slug}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });

export const deletePage = (projectId, slug) =>
  fetchJSON(`/api/projects/${projectId}/pages/${slug}`, { method: "DELETE" });

export const listVersions = (projectId, slug) =>
  fetchJSON(`/api/projects/${projectId}/pages/${slug}/versions`);

export const listVersionFiles = (projectId, slug, version) =>
  fetchJSON(
    `/api/projects/${projectId}/pages/${slug}/versions/${version}/files`
  );

export const listMessages = (projectId, slug) =>
  fetchJSON(`/api/projects/${projectId}/pages/${slug}/messages`);

export const createMessage = (projectId, slug, data) =>
  fetchJSON(`/api/projects/${projectId}/pages/${slug}/messages`, {
    method: "POST",
    body: JSON.stringify(data),
  });

export const fetchGuides = (projectId) =>
  fetchJSON(`/api/projects/${projectId}/guides`);

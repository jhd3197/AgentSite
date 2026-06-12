import { fetchJSON } from "./client";

// Workspace templates for project-mode generation.
// Each: { id, name, description, kind: "static" | "node" }
export const listTemplates = () => fetchJSON("/api/templates");

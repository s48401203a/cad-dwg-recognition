const jsonHeaders = { "Content-Type": "application/json" };

async function request(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      message = body.detail || message;
    } catch {
      message = await response.text();
    }
    throw new Error(message);
  }
  return response.json();
}

async function download(url) {
  const response = await fetch(new URL(url, window.location.origin));
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.blob();
}

export const api = {
  health() {
    return request("/api/health");
  },
  upload(file) {
    const form = new FormData();
    form.append("file", file);
    return request("/api/upload", { method: "POST", body: form });
  },
  parse(payload) {
    return request("/api/parse", {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify(payload),
    });
  },
  listProjects({ includeArchived = false, scopeProjectId = null } = {}) {
    const params = new URLSearchParams();
    if (includeArchived) params.set("include_archived", "true");
    if (scopeProjectId) params.set("scope_project_id", scopeProjectId);
    const query = params.toString();
    return request(`/api/projects${query ? `?${query}` : ""}`);
  },
  importProjectPackage(path) {
    return request("/api/project-packages/import", {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({ path }),
    });
  },
  createProject(payload) {
    return request("/api/projects", {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify(payload),
    });
  },
  getProject(projectId) {
    return request(`/api/projects/${projectId}`);
  },
  reparseProject(projectId, payload = {}) {
    return request(`/api/projects/${projectId}/reparse`, {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify(payload),
    });
  },
  archiveProject(projectId) {
    return request(`/api/projects/${projectId}/archive`, { method: "POST" });
  },
  restoreProject(projectId) {
    return request(`/api/projects/${projectId}/restore`, { method: "POST" });
  },
  deleteProject(projectId, confirmText) {
    const params = new URLSearchParams({ confirm: confirmText || "" });
    return request(`/api/projects/${projectId}?${params.toString()}`, { method: "DELETE" });
  },
  listSiteProfiles() {
    return request("/api/site-profiles");
  },
  exportProject(projectId, options = {}) {
    const params = new URLSearchParams();
    const drawingId = options.drawing_id || options.drawingId;
    if (drawingId) params.set("drawing_id", drawingId);
    if (options.include_all_drawings) params.set("include_all_drawings", "true");
    const query = params.toString();
    return request(`/api/projects/${projectId}/export${query ? `?${query}` : ""}`);
  },
  exportStaticProject(projectId, payload = {}) {
    return request(`/api/projects/${projectId}/export-static`, {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify(payload),
    });
  },
  shareProjectLink(projectId, drawingId = null) {
    const params = new URLSearchParams();
    if (drawingId) params.set("drawing_id", drawingId);
    const query = params.toString();
    return request(`/api/projects/${projectId}/share-link${query ? `?${query}` : ""}`);
  },
  openProjectFolder(projectId) {
    return request(`/api/projects/${projectId}/open-folder`, { method: "POST" });
  },
  openProjectSourceFile(projectId, drawingId = null) {
    return request(`/api/projects/${projectId}/open-source-file`, {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({ drawing_id: drawingId }),
    });
  },
  captureVisualAudit(projectId, payload = {}) {
    return request(`/api/projects/${projectId}/visual-audit/capture`, {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify(payload),
    });
  },
  download,
};

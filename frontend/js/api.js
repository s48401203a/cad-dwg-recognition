const jsonHeaders = { "Content-Type": "application/json" };
const TOKEN_STORAGE_KEY = "cad_access_token";

// 访问令牌：由启动脚本通过 ?token=... 传入（局域网模式必须），回环模式通常为空。
// 只保存在本机 localStorage，不写入日志、不发送到第三方。
// 同时会用它建立 HttpOnly 会话 cookie，使浏览器直接打开 /exports/ 下的导出文件也能通过校验
// （<a href> 导航无法附带自定义请求头，只能靠 cookie）。
export function captureAccessToken() {
  try {
    const params = new URLSearchParams(window.location.search);
    const token = params.get("token");
    if (token) {
      window.localStorage.setItem(TOKEN_STORAGE_KEY, token);
      // 立刻把 URL 里的令牌清掉，避免留在历史记录/被复制出去。
      params.delete("token");
      const query = params.toString();
      window.history.replaceState({}, "", `${window.location.pathname}${query ? `?${query}` : ""}${window.location.hash}`);
    }
    return window.localStorage.getItem(TOKEN_STORAGE_KEY) || "";
  } catch {
    return "";
  }
}

export function accessToken() {
  try {
    return window.localStorage.getItem(TOKEN_STORAGE_KEY) || "";
  } catch {
    return "";
  }
}

export function forgetAccessToken() {
  try {
    window.localStorage.removeItem(TOKEN_STORAGE_KEY);
  } catch {
    /* localStorage 不可用时忽略 */
  }
}

function withToken(options = {}) {
  const token = accessToken();
  if (!token) return options;
  const headers = new Headers(options.headers || {});
  if (!headers.has("X-CAD-Token")) headers.set("X-CAD-Token", token);
  return { ...options, headers, credentials: options.credentials || "same-origin" };
}

//: 认证失效监听器：由 app.js 注册，用来弹出登录界面。
const authListeners = new Set();

export function onAuthRequired(listener) {
  authListeners.add(listener);
  return () => authListeners.delete(listener);
}

function notifyAuthRequired(status) {
  authListeners.forEach((listener) => {
    try {
      listener(status);
    } catch {
      /* 监听器异常不应影响请求流程 */
    }
  });
}

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request(url, options = {}) {
  const response = await fetch(url, withToken(options));
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      message = body.detail || message;
    } catch {
      message = await response.text();
    }
    if (response.status === 401) notifyAuthRequired(401);
    throw new ApiError(message, response.status);
  }
  return response.json();
}

async function download(url) {
  const response = await fetch(new URL(url, window.location.origin), withToken());
  if (!response.ok) {
    if (response.status === 401) notifyAuthRequired(401);
    throw new ApiError(`${response.status} ${response.statusText}`, response.status);
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
    // 生成分享页会写文件（有副作用），因此用 POST。
    // 返回的链接只携带作用域限于该导出文件的分享令牌，不含主访问令牌。
    return request(`/api/projects/${projectId}/share-link`, {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({ drawing_id: drawingId || null }),
    });
  },
  authSession() {
    return request("/api/auth/session");
  },
  authLogin(token) {
    return request("/api/auth/login", { method: "POST", headers: jsonHeaders, body: JSON.stringify({ token }) });
  },
  authLogout() {
    return request("/api/auth/logout", { method: "POST" });
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
  getModelCatalog() {
    return request("/api/model-catalog");
  },
  ensurePlacementScene(projectId) {
    return request(`/api/projects/${projectId}/placement/ensure`, { method: "POST" });
  },
  getModelOverrides(projectId) {
    return request(`/api/projects/${projectId}/model-overrides`);
  },
  saveModelOverrides(projectId, payload) {
    return request(`/api/projects/${projectId}/model-overrides`, {
      method: "PUT",
      headers: jsonHeaders,
      body: JSON.stringify(payload),
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

import { accessToken } from "./api.js";

export class Logger {
  constructor(panel) {
    this.panel = panel;
    this.lines = [];
    this.socket = null;
    this.retryDelay = 3000;
    this.listeners = new Set();
  }

  connect() {
    // 只应在认证完成（或无需认证）之后调用：启用访问令牌时，未认证的握手会被拒绝。
    if (this.socket && this.socket.readyState <= WebSocket.OPEN) return;
    const protocol = location.protocol === "https:" ? "wss" : "ws";
    // 令牌在 app 启动时从 ?token= 收敛到 localStorage；这里每次重连都重新读取，
    // 保证局域网/启用令牌模式下 WebSocket 也能通过鉴权。
    const token = accessToken();
    const query = token ? `?token=${encodeURIComponent(token)}` : "";
    this.socket = new WebSocket(`${protocol}://${location.host}/ws/logs${query}`);
    this.socket.addEventListener("open", () => {
      this.retryDelay = 3000;
      this.add("INFO", "日志通道已连接");
    });
    this.socket.addEventListener("message", (event) => {
      try {
        const payload = JSON.parse(event.data);
        this.add(payload.level || "INFO", payload.message || "", payload.time);
      } catch {
        this.add("INFO", event.data);
      }
    });
    this.socket.addEventListener("close", () => {
      // 认证失败或服务端拒绝时不要疯狂重连：退避重试，且不再向控制台抛错
      // （WebSocket 握手失败是浏览器层面的 console error，不可抑制，
      //  因此未认证时压根不应该发起连接）。
      const delay = this.retryDelay || 3000;
      this.retryDelay = Math.min(delay * 2, 30000);
      window.setTimeout(() => this.connect(), delay);
    });
  }

  disconnect() {
    if (!this.socket) return;
    const socket = this.socket;
    this.socket = null;
    try {
      socket.close();
    } catch {
      /* 忽略关闭异常 */
    }
  }

  add(level, message, time = null) {
    const stamp = time || new Date().toLocaleTimeString("zh-CN", { hour12: false });
    const line = { level: level.toUpperCase(), message, time: stamp };
    this.lines.push(line);
    if (this.lines.length > 100) this.lines.shift();
    this.render();
    this.listeners.forEach((listener) => {
      try {
        listener(line);
      } catch {
        // 日志渲染不应被旁路监听器中断。
      }
    });
  }

  onLine(listener) {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  render() {
    this.panel.innerHTML = this.lines
      .map((line) => `<div class="log-line">[${line.time}] <span class="level-${line.level}">${line.level}</span>: ${escapeHtml(line.message)}</div>`)
      .join("");
    this.panel.scrollTop = this.panel.scrollHeight;
  }
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

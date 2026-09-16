import { accessToken } from "./api.js";

export class Logger {
  constructor(panel) {
    this.panel = panel;
    this.lines = [];
    this.socket = null;
    this.listeners = new Set();
  }

  connect() {
    const protocol = location.protocol === "https:" ? "wss" : "ws";
    const token = accessToken();
    const query = token ? `?token=${encodeURIComponent(token)}` : "";
    this.socket = new WebSocket(`${protocol}://${location.host}/ws/logs${query}`);
    this.socket.addEventListener("open", () => this.add("INFO", "日志通道已连接"));
    this.socket.addEventListener("message", (event) => {
      try {
        const payload = JSON.parse(event.data);
        this.add(payload.level || "INFO", payload.message || "", payload.time);
      } catch {
        this.add("INFO", event.data);
      }
    });
    this.socket.addEventListener("close", () => {
      this.add("WARNING", "日志通道断开，3 秒后重连");
      window.setTimeout(() => this.connect(), 3000);
    });
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

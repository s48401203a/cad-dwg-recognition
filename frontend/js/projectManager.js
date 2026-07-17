import { api } from "./api.js";

export class ProjectManager {
  constructor({ modal, nameInput, saveDirInput, list, modalList, confirmButton, cancelButton, logger, onMutation, scopeProjectId = null }) {
    this.modal = modal;
    this.nameInput = nameInput;
    this.saveDirInput = saveDirInput;
    this.list = list;
    this.modalList = modalList;
    this.confirmButton = confirmButton;
    this.cancelButton = cancelButton;
    this.logger = logger;
    this.onMutation = onMutation;
    this.projects = [];
    this.selected = null;
    this.pendingResolve = null;
    this.includeArchived = false;
    this.scopeProjectId = scopeProjectId;
    this.onSelect = null;
    this.defaultName = "未命名弱电项目";
    this.cancelButton.addEventListener("click", () => this.close(null));
    this.confirmButton.addEventListener("click", () => this.confirm());
  }

  async refresh(onSelect) {
    try {
      this.onSelect = onSelect || this.onSelect;
      this.projects = await api.listProjects({
        includeArchived: this.includeArchived,
        scopeProjectId: this.scopeProjectId,
      });
      this.renderList(this.list, this.onSelect, {
        showToolbar: !this.scopeProjectId,
        showActions: !this.scopeProjectId,
      });
      this.renderList(this.modalList, (project) => {
        if (isArchived(project)) {
          this.logger?.add("WARNING", "归档项目为只读状态，恢复后才能作为解析目标");
          return;
        }
        this.selected = project;
        this.nameInput.value = project.name;
        this.saveDirInput.value = project.save_dir || "";
      }, { projects: this.projects.filter((project) => !isArchived(project)) });
    } catch (error) {
      this.logger?.add("WARNING", `项目列表读取失败: ${error.message}`);
    }
  }

  open(defaultName = "未命名弱电项目") {
    this.defaultName = defaultName;
    this.selected = null;
    this.nameInput.value = defaultName;
    if (!this.saveDirInput.value) this.saveDirInput.value = "";
    this.modal.classList.add("open");
    return new Promise((resolve) => {
      this.pendingResolve = resolve;
    });
  }

  close(project) {
    this.modal.classList.remove("open");
    if (this.pendingResolve) this.pendingResolve(project);
    this.pendingResolve = null;
  }

  async confirm() {
    if (this.selected && isArchived(this.selected)) {
      this.logger?.add("WARNING", "归档项目不能作为解析目标，请先恢复项目");
      return;
    }
    if (this.selected && this.selected.name === this.nameInput.value && this.selected.save_dir === this.saveDirInput.value) {
      this.close(this.selected);
      return;
    }
    try {
      const project = await api.createProject({
        name: this.nameInput.value.trim() || "未命名项目",
        save_dir: this.saveDirInput.value.trim() || null,
      });
      this.projects.unshift(project);
      this.close(project);
    } catch (error) {
      this.logger?.add("ERROR", `项目创建失败: ${error.message}`);
    }
  }

  renderList(container, onSelect, options = {}) {
    if (!container) return;
    const projects = options.projects || this.projects;
    const toolbar = options.showToolbar
      ? `<div class="project-toolbar">
          <button type="button" data-project-new>新建项目</button>
          <button type="button" data-project-import-package>导入项目包</button>
          <button type="button" data-project-toggle-archived>${this.includeArchived ? "隐藏归档" : "显示归档"}</button>
        </div>`
      : "";
    if (!projects.length) {
      container.innerHTML = `${toolbar}<div class="project-item"><strong>暂无项目</strong><span>解析时会自动创建项目记录</span></div>`;
      this.bindToolbar(container);
      return;
    }
    container.innerHTML = toolbar + projects
      .map(
        (project) => `<div class="project-item${isArchived(project) ? " archived" : ""}" data-project="${project.id}">
          <strong>${escapeHtml(project.name)}${isArchived(project) ? '<em class="project-status">已归档</em>' : ""}</strong>
          <span>${project.drawings?.length || 0} 张图纸 · ${escapeHtml(project.save_dir || "")}</span>
          ${options.showActions ? this.renderActions(project) : ""}
        </div>`,
      )
      .join("");
    this.bindToolbar(container);
    container.querySelectorAll("[data-project]").forEach((item) => {
      item.addEventListener("click", () => {
        const project = this.projects.find((candidate) => candidate.id === item.dataset.project);
        if (project && onSelect) onSelect(project);
      });
    });
    container.querySelectorAll("[data-project-action]").forEach((button) => {
      button.addEventListener("click", (event) => {
        event.stopPropagation();
        const project = this.projects.find((candidate) => candidate.id === button.dataset.projectId);
        if (project) this.handleAction(project, button.dataset.projectAction);
      });
    });
  }

  renderActions(project) {
    if (isArchived(project)) {
      return `<div class="project-actions">
        <button type="button" data-project-action="restore" data-project-id="${project.id}">恢复</button>
        <button type="button" data-project-action="delete" data-project-id="${project.id}">删除</button>
      </div>`;
    }
    return `<div class="project-actions">
      <button type="button" data-project-action="archive" data-project-id="${project.id}">归档</button>
    </div>`;
  }

  bindToolbar(container) {
    const createNew = container.querySelector("[data-project-new]");
    if (createNew) createNew.addEventListener("click", () => {
      this.selected = null;
      this.nameInput.value = this.defaultName;
      this.saveDirInput.value = "";
      this.nameInput.focus();
      this.logger?.add("INFO", "已切换为新建项目，请填写项目名和保存目录后确认");
    });
    const toggle = container.querySelector("[data-project-toggle-archived]");
    if (toggle) toggle.addEventListener("click", async () => {
      this.includeArchived = !this.includeArchived;
      await this.refresh(this.onSelect);
    });
    const importer = container.querySelector("[data-project-import-package]");
    if (importer) importer.addEventListener("click", async () => {
      const packagePath = window.prompt("输入项目包文件夹路径（包含 project.json）");
      if (!packagePath) return;
      try {
        const project = await api.importProjectPackage(packagePath.trim());
        this.logger?.add("SUCCESS", `已导入项目包 ${project.name}`);
        await this.refresh(this.onSelect);
        if (typeof this.onSelect === "function") await this.onSelect(project);
      } catch (error) {
        this.logger?.add("ERROR", `项目包导入失败: ${error.message}`);
      }
    });
  }

  async handleAction(project, action) {
    try {
      if (action === "archive") {
        if (!window.confirm(`归档项目“${project.name}”？归档后将自动生成静态 HTML 快照保留模型可视化。`)) return;
        this.logger?.add("INFO", `正在归档项目 ${project.name}（生成静态快照中...）`);
        await api.archiveProject(project.id);
        this.logger?.add("SUCCESS", `已归档项目 ${project.name}（静态快照已生成）`);
      } else if (action === "restore") {
        this.logger?.add("INFO", `正在恢复项目 ${project.name}（如需要会自动重解析）...`);
        await api.restoreProject(project.id);
        this.logger?.add("SUCCESS", `已恢复项目 ${project.name}`);
      } else if (action === "delete") {
        const confirmText = window.prompt(`删除归档项目会先备份。请输入项目ID确认删除：${project.id}`);
        if (confirmText !== project.id) return;
        await api.deleteProject(project.id, confirmText);
        this.logger?.add("SUCCESS", `已删除归档项目 ${project.name}`);
      }
      await this.refresh();
      this.onMutation?.(project, action);
      if (action === "restore" && typeof this.onSelect === "function") {
        const restored = this.projects.find((item) => item.id === project.id);
        if (restored) {
          await this.onSelect(restored);
        }
      }
    } catch (error) {
      this.logger?.add("ERROR", `项目${actionLabel(action)}失败: ${error.message}`);
    }
  }
}

function isArchived(project) {
  return project?.status === "archived";
}

function actionLabel(action) {
  return { archive: "归档", restore: "恢复", delete: "删除" }[action] || "操作";
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

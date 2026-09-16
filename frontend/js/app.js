import { api, captureAccessToken } from "./api.js?v=54";

// 启动脚本可能通过 ?token=... 传入访问令牌（局域网模式必须）；先收敛再发请求。
captureAccessToken();
import { Logger } from "./logger.js";
import { ProjectManager } from "./projectManager.js?v=6";
import { SceneBuilder } from "./renderer/SceneBuilder.js?v=89";
import { PlacementStudio } from "./placementStudio.js?v=15";

const LAYER_ORDER_STORAGE_KEY = "cad-layer-card-order-v1";
const LAYER_VISIBILITY_STORAGE_KEY = "cad-layer-card-visibility-v1";
const PANEL_SECTION_STATE_STORAGE_KEY = "cad-panel-section-state-v1";
const LAST_PROJECT_STORAGE_KEY = "cad-last-project-selection-v1";
const DISPLAY_MODE_STORAGE_KEY = "cad-display-mode-v1";
const FRAME_VIEW_FILTER_STORAGE_KEY = "cad-frame-view-filters-v1";
const FRAME_PANEL_STATE_STORAGE_KEY = "cad-frame-panel-state-v1";
const MODEL_SCALE_STORAGE_KEY = "cad-device-model-scale-percent-v4";
const UPLOAD_PARSE_PROMPT_TIMEOUT_MS = 20_000;
const DEFAULT_MODEL_SCALE_PERCENT = 100;
const MIN_MODEL_SCALE_PERCENT = 100;
const MAX_MODEL_SCALE_PERCENT = 300;
const STATIC_EXPORT_EXTENSION = ".html";
const AUTO_PERFORMANCE_LAYER_OFF = [
  "labels",
  "coverage.ap",
  "coverage.fisheye",
  "coverage.dome",
  "coverage.bullet",
  "spotlights",
  "cables.spotlight",
];
const PERFORMANCE_DEVICE_THRESHOLD = 260;
const PERFORMANCE_STRUCTURE_THRESHOLD = 520;
const PERFORMANCE_SCORE_THRESHOLD = 760;
const LOCAL_SHARE_HOSTS = new Set(["localhost", "127.0.0.1", "0.0.0.0", "::1", "[::1]"]);
const PARSE_PROGRESS_STAGES = {
  upload: { title: "选择 / 上传", percent: 12 },
  dxf: { title: "DXF读取", percent: 35 },
  rules: { title: "规则识别", percent: 55 },
  semantic: { title: "生成semantic", percent: 72 },
  scene: { title: "构建3D", percent: 88 },
  audit: { title: "审计截图", percent: 92 },
  complete: { title: "完成", percent: 100 },
  failed: { title: "失败", percent: 100 },
};

const state = {
  uploads: [],
  project: null,
  projectSource: "auto",
  semantic: null,
  siteProfiles: ["generic"],
  siteProfilesExplicit: false,
  siteProfileResolve: null,
  progressHideTimer: null,
  parsePromptTimer: null,
  progressPercent: 0,
  progressCompleted: false,
  framePreviewMap: null,
  framePreviewDrag: null,
  frameViewFilters: {},
  framePanelCollapsed: false,
  framePreviewCollapsed: false,
  framePanelHidden: true,
  layerControlsTouched: false,
  performanceProfileKey: null,
  loadGeneration: 0,
  frameViewFiltersByProject: {},
};

const dom = {
  fileInput: document.getElementById("fileInput"),
  uploadButton: document.getElementById("uploadButton"),
  projectButton: document.getElementById("projectButton"),
  parseButton: document.getElementById("parseButton"),
  visualAuditButton: document.getElementById("visualAuditButton"),
  staticExportButton: document.getElementById("staticExportButton"),
  shareLinkButton: document.getElementById("shareLinkButton"),
  openProjectDirButton: document.getElementById("openProjectDirButton"),
  openSourceFileButton: document.getElementById("openSourceFileButton"),
  siteProfileSummary: document.getElementById("siteProfileSummary"),
  siteProfileModal: document.getElementById("siteProfileModal"),
  siteProfileGeneric: document.getElementById("siteProfileGeneric"),
  siteProfileExpress: document.getElementById("siteProfileExpress"),
  siteProfileSupplyChain: document.getElementById("siteProfileSupplyChain"),
  confirmSiteProfileButton: document.getElementById("confirmSiteProfileButton"),
  cancelSiteProfileButton: document.getElementById("cancelSiteProfileButton"),
  projectTitle: document.getElementById("projectTitle"),
  projectSubtitle: document.getElementById("projectSubtitle"),
  drawingList: document.getElementById("drawingList"),
  reviewList: document.getElementById("reviewList"),
  processNotesList: document.getElementById("processNotesList"),
  removalNotesList: document.getElementById("removalNotesList"),
  projectList: document.getElementById("projectList"),
  sidePanel: document.getElementById("sidePanel"),
  layerList: document.getElementById("layerList"),
  logPanel: document.getElementById("logPanel"),
  canvasWrap: document.getElementById("canvasWrap"),
  fullscreenButton: document.getElementById("fullscreenButton"),
  scene: document.getElementById("scene"),
  dropHint: document.getElementById("dropHint"),
  parseProgressPanel: document.getElementById("parseProgressPanel"),
  parseProgressStage: document.getElementById("parseProgressStage"),
  parseProgressPercent: document.getElementById("parseProgressPercent"),
  parseProgressBar: document.getElementById("parseProgressBar"),
  parseProgressSummary: document.getElementById("parseProgressSummary"),
  uploadParsePrompt: document.getElementById("uploadParsePrompt"),
  uploadParsePromptSummary: document.getElementById("uploadParsePromptSummary"),
  uploadParseNowButton: document.getElementById("uploadParseNowButton"),
  uploadParseDismissButton: document.getElementById("uploadParseDismissButton"),
  frameDetectionBar: document.getElementById("frameDetectionBar"),
  frameSummary: document.getElementById("frameSummary"),
  baseViewSummary: document.getElementById("baseViewSummary"),
  canonicalViewsSummary: document.getElementById("canonicalViewsSummary"),
  framePanelToggle: document.getElementById("framePanelToggle"),
  framePreviewToggle: document.getElementById("framePreviewToggle"),
  framePanelHide: document.getElementById("framePanelHide"),
  framePanelRestore: document.getElementById("framePanelRestore"),
  framePanelBody: document.getElementById("framePanelBody"),
  frameSwitchList: document.getElementById("frameSwitchList"),
  framePreview: document.getElementById("framePreview"),
  framePreviewSvg: document.getElementById("framePreviewSvg"),
  reparseForm: document.getElementById("reparseForm"),
  bboxInput: document.getElementById("bboxInput"),
  reparseButton: document.getElementById("reparseButton"),
  inspector: document.getElementById("inspector"),
  displayModeButton: document.getElementById("displayModeButton"),
  opacitySlider: document.getElementById("opacitySlider"),
  opacityValue: document.getElementById("opacityValue"),
  modelScaleSlider: document.getElementById("modelScaleSlider"),
  modelScaleValue: document.getElementById("modelScaleValue"),
  stats: {
    devices: document.getElementById("statDevices"),
    cables: document.getElementById("statCables"),
    cameras: document.getElementById("statCameras"),
    entities: document.getElementById("statEntities"),
    metricDevices: document.getElementById("metricDevices"),
    metricCameras: document.getElementById("metricCameras"),
    metricAps: document.getElementById("metricAps"),
    metricReview: document.getElementById("metricReview"),
  },
};

const logger = new Logger(dom.logPanel);
logger.connect();
logger.onLine((line) => syncProgressFromLog(line));

const scene = new SceneBuilder(dom.scene, dom.canvasWrap);
scene.onSelect = (entity, kind) => renderInspector(entity, kind);

const placement = new PlacementStudio({
  api,
  scene,
  logger,
  getProject: () => state.project,
  applySemantic: (semantic, options = {}) => applySemantic(semantic, options),
  onStatus: () => {},
});
placement.attach();

const reverseValidationMode = isReverseValidationMode();
const initialProjectTarget = getInitialProjectTarget();
const projectManager = new ProjectManager({
  modal: document.getElementById("projectModal"),
  nameInput: document.getElementById("projectNameInput"),
  saveDirInput: document.getElementById("saveDirInput"),
  list: dom.projectList,
  modalList: document.getElementById("modalProjectList"),
  confirmButton: document.getElementById("confirmProjectButton"),
  cancelButton: document.getElementById("cancelProjectButton"),
  logger,
  onMutation: handleProjectMutation,
  scopeProjectId: initialProjectTarget?.scoped ? initialProjectTarget.projectId : null,
});

init();

async function init() {
  document.body.classList.toggle("reverse-validation-mode", reverseValidationMode);
  restoreLayerPreferences();
  applySavedDisplayMode();
  applySavedFramePanelState();
  bindEvents();
  initializeLayerVisibilityFromInputs();
  renderSiteProfileSummary();
  renderDrawingList();
  if (reverseValidationMode && !initialProjectTarget) {
    renderReverseValidationLanding();
  }
  try {
    const health = await api.health();
    logger.add("SUCCESS", `服务就绪，ODA ${health.oda_available ? "可用" : "未检测到"}`);
  } catch (error) {
    logger.add("ERROR", `服务连接失败: ${error.message}`);
  }
  await refreshProjects({
    autoLoadLatest: !initialProjectTarget && !reverseValidationMode,
    preferredProjectId: initialProjectTarget?.projectId,
    preferredDrawingId: initialProjectTarget?.drawingId,
  });
}

function initializeLayerVisibilityFromInputs() {
  document.querySelectorAll("[data-layer]").forEach((input) => {
    scene.setLayerVisibility(input.dataset.layer, input.checked);
  });
  syncLayerCardControls();
}

function bindEvents() {
  dom.uploadButton.addEventListener("click", () => {
    ensureDefaultSiteProfiles();
    dom.fileInput.click();
  });
  dom.siteProfileSummary?.addEventListener("click", () => openSiteProfileModal());
  dom.siteProfileSummary?.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      openSiteProfileModal();
    }
  });
  dom.fileInput.addEventListener("change", () => uploadFiles([...dom.fileInput.files]));
  dom.projectButton.addEventListener("click", async () => {
    if (reverseValidationMode && !initialProjectTarget) {
      await createReverseValidationProject(defaultProjectName());
      return;
    }
    const project = await projectManager.open(defaultProjectName());
    if (project) await loadProject(project);
  });
  dom.parseButton.addEventListener("click", parseUploads);
  dom.uploadParseNowButton?.addEventListener("click", () => {
    hideUploadParsePrompt();
    parseUploads();
  });
  dom.uploadParseDismissButton?.addEventListener("click", () => hideUploadParsePrompt());
  dom.visualAuditButton?.addEventListener("click", captureVisualAudit);
  dom.staticExportButton?.addEventListener("click", exportStaticPreview);
  dom.shareLinkButton?.addEventListener("click", copyProjectShareLink);
  dom.openProjectDirButton?.addEventListener("click", openProjectDirectory);
  dom.openSourceFileButton?.addEventListener("click", openCurrentSourceFile);
  dom.fullscreenButton?.addEventListener("click", toggleFullscreenView);
  document.addEventListener("keydown", handleGlobalShortcuts);
  document.addEventListener("fullscreenchange", () => {
    setFullscreenView(Boolean(document.fullscreenElement));
  });
  initTopActionMenus();
  dom.reparseForm?.addEventListener("submit", reparseCurrentProject);
  dom.bboxInput?.addEventListener("input", syncProjectActionButtons);
  dom.framePanelToggle?.addEventListener("click", () => setFramePanelCollapsed(!state.framePanelCollapsed));
  dom.framePreviewToggle?.addEventListener("click", () => setFramePreviewCollapsed(!state.framePreviewCollapsed));
  dom.framePanelHide?.addEventListener("click", () => setFramePanelHidden(true));
  dom.framePanelRestore?.addEventListener("click", () => setFramePanelHidden(false));
  initFramePreviewPicker();
  dom.confirmSiteProfileButton?.addEventListener("click", confirmSiteProfiles);
  dom.cancelSiteProfileButton?.addEventListener("click", () => closeSiteProfileModal(false));

  dom.canvasWrap.addEventListener("dragover", (event) => {
    event.preventDefault();
  });
  dom.canvasWrap.addEventListener("drop", (event) => {
    event.preventDefault();
    uploadFiles([...event.dataTransfer.files].filter((file) => /\.(dwg|dxf)$/i.test(file.name)));
  });

  document.querySelectorAll("[data-layer]").forEach((input) => {
    input.addEventListener("change", () => {
      setLayerInputs([input], input.checked);
    });
  });
  initLayerLegendControls();
  initLayerDragOrder();
  initPanelSectionControls();
  document.querySelectorAll("[data-view]").forEach((button) => {
    button.addEventListener("click", () => {
      const result = scene.setView(button.dataset.view);
      if (button.dataset.view === "zone" && result?.label) {
        button.textContent = result.label;
      }
    });
  });
  dom.displayModeButton.addEventListener("click", () => {
    const nextMode = scene.getDetailMode() === "full" ? "adaptive" : "full";
    scene.setDetailMode(nextMode);
    renderDisplayMode(nextMode);
    localStorage.setItem(DISPLAY_MODE_STORAGE_KEY, nextMode);
  });
  dom.opacitySlider.addEventListener("input", () => {
    dom.opacityValue.textContent = `${dom.opacitySlider.value}%`;
    scene.setOpacity(Number(dom.opacitySlider.value));
  });
  initModelScaleControl();
  renderDisplayMode(scene.getDetailMode());
}

function toggleFullscreenView() {
  const enabled = !document.body.classList.contains("fullscreen-view");
  setFullscreenView(enabled);
}

function setFullscreenView(enabled) {
  const active = Boolean(enabled);
  document.body.classList.toggle("fullscreen-view", active);
  if (dom.fullscreenButton) {
    dom.fullscreenButton.textContent = active ? "退出全屏" : "全屏";
    dom.fullscreenButton.setAttribute("aria-pressed", active ? "true" : "false");
    dom.fullscreenButton.title = active ? "退出全屏查看 (Esc)" : "全屏查看 (Enter / Alt+Enter)";
  }
  window.setTimeout(() => scene.resize(), 80);
}

function handleGlobalShortcuts(event) {
  if (event.defaultPrevented) return;
  if (event.key === "Escape" && document.querySelector(".action-menu.open")) {
    closeTopActionMenus();
    return;
  }
  const fullscreen = document.body.classList.contains("fullscreen-view");
  if (event.key === "Escape" && fullscreen) {
    event.preventDefault();
    setFullscreenView(false);
    return;
  }
  if (event.key !== "Enter" || isShortcutBlockedTarget(event.target)) return;
  const plainEnter = !event.altKey && !event.ctrlKey && !event.metaKey && !event.shiftKey;
  if ((plainEnter || event.altKey) && !fullscreen) {
    event.preventDefault();
    setFullscreenView(true);
  }
}

function isShortcutBlockedTarget(target) {
  if (!(target instanceof Element)) return false;
  return Boolean(target.closest("input, textarea, select, button, a, [contenteditable='true'], [role='button'], [role='menuitem']"));
}

function initTopActionMenus() {
  document.querySelectorAll("[data-action-menu] .menu-trigger").forEach((trigger) => {
    trigger.addEventListener("click", (event) => {
      event.stopPropagation();
      const menu = trigger.closest("[data-action-menu]");
      const open = menu?.classList.contains("open");
      closeTopActionMenus();
      if (menu && !open) {
        menu.classList.add("open");
        trigger.setAttribute("aria-expanded", "true");
      }
    });
  });
  document.querySelectorAll("[data-action-menu] .menu-panel button").forEach((button) => {
    button.addEventListener("click", () => closeTopActionMenus());
  });
  document.addEventListener("click", (event) => {
    if (event.target instanceof Element && event.target.closest("[data-action-menu]")) return;
    closeTopActionMenus();
  });
}

function closeTopActionMenus() {
  document.querySelectorAll("[data-action-menu].open").forEach((menu) => {
    menu.classList.remove("open");
    menu.querySelector(".menu-trigger")?.setAttribute("aria-expanded", "false");
  });
}

function initModelScaleControl() {
  if (!dom.modelScaleSlider || !dom.modelScaleValue) return;
  const savedValue = Number(localStorage.getItem(MODEL_SCALE_STORAGE_KEY) || dom.modelScaleSlider.value || DEFAULT_MODEL_SCALE_PERCENT);
  const initialValue = clampModelScale(savedValue);
  dom.modelScaleSlider.value = String(initialValue);
  renderModelScaleValue(initialValue);
  scene.setModelScalePercent(initialValue);
  const updateModelScale = () => {
    const value = clampModelScale(Number(dom.modelScaleSlider.value));
    dom.modelScaleSlider.value = String(value);
    renderModelScaleValue(value);
    localStorage.setItem(MODEL_SCALE_STORAGE_KEY, String(value));
    scene.setModelScalePercent(value);
  };
  dom.modelScaleSlider.addEventListener("input", updateModelScale);
  dom.modelScaleSlider.addEventListener("change", updateModelScale);
}

function clampModelScale(value) {
  if (!Number.isFinite(value)) return DEFAULT_MODEL_SCALE_PERCENT;
  return Math.max(MIN_MODEL_SCALE_PERCENT, Math.min(MAX_MODEL_SCALE_PERCENT, Math.round(value / 5) * 5));
}

function renderModelScaleValue(value) {
  dom.modelScaleValue.textContent = `${value}%`;
}

function initLayerDragOrder() {
  if (!dom.layerList) return;
  let draggedCard = null;
  let suppressClick = false;
  dom.layerList.querySelectorAll("[data-layer-card]").forEach((card) => {
    card.setAttribute("role", "button");
    card.tabIndex = 0;
    card.addEventListener("click", () => {
      if (suppressClick) return;
      toggleLayerCard(card);
    });
    card.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      event.preventDefault();
      toggleLayerCard(card);
    });
    card.addEventListener("dragstart", (event) => {
      draggedCard = card;
      suppressClick = true;
      card.classList.add("dragging");
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", card.dataset.layerCard);
    });
    card.addEventListener("dragover", (event) => {
      event.preventDefault();
      if (!draggedCard || draggedCard === card) return;
      const cards = [...dom.layerList.querySelectorAll("[data-layer-card]")];
      const draggedIndex = cards.indexOf(draggedCard);
      const targetIndex = cards.indexOf(card);
      if (draggedIndex < 0 || targetIndex < 0) return;
      dom.layerList.insertBefore(draggedCard, draggedIndex < targetIndex ? card.nextSibling : card);
    });
    card.addEventListener("dragend", () => {
      card.classList.remove("dragging");
      draggedCard = null;
      saveLayerOrder();
      window.setTimeout(() => {
        suppressClick = false;
      }, 120);
    });
  });
}

function restoreLayerPreferences() {
  applySavedLayerOrder();
  applySavedLayerVisibility();
}

function applySavedDisplayMode() {
  const savedMode = localStorage.getItem(DISPLAY_MODE_STORAGE_KEY);
  if (savedMode !== "full" && savedMode !== "adaptive") return;
  scene.setDetailMode(savedMode);
  renderDisplayMode(savedMode);
}

function applySavedFramePanelState() {
  const saved = readStorageObject(FRAME_PANEL_STATE_STORAGE_KEY);
  if (!saved) return;
  if ("collapsed" in saved) setFramePanelCollapsed(Boolean(saved.collapsed), { skipRender: true, skipSave: true });
  if ("previewCollapsed" in saved) setFramePreviewCollapsed(Boolean(saved.previewCollapsed), { skipSave: true });
  if ("hidden" in saved) setFramePanelHidden(Boolean(saved.hidden), { skipSave: true });
}

function applySavedLayerOrder() {
  if (!dom.layerList) return;
  let savedOrder = [];
  try {
    savedOrder = JSON.parse(localStorage.getItem(LAYER_ORDER_STORAGE_KEY) || "[]");
  } catch {
    savedOrder = [];
  }
  if (!Array.isArray(savedOrder) || !savedOrder.length) return;
  const cards = [...dom.layerList.querySelectorAll("[data-layer-card]")];
  const byLayer = new Map(cards.map((card) => [card.dataset.layerCard, card]));
  savedOrder.forEach((layer) => {
    const card = byLayer.get(layer);
    if (card) {
      dom.layerList.appendChild(card);
      byLayer.delete(layer);
    }
  });
  byLayer.forEach((card) => dom.layerList.appendChild(card));
}

function saveLayerOrder() {
  const order = [...dom.layerList.querySelectorAll("[data-layer-card]")].map((card) => card.dataset.layerCard);
  localStorage.setItem(LAYER_ORDER_STORAGE_KEY, JSON.stringify(order));
}

function applySavedLayerVisibility() {
  const savedState = readLayerVisibilityState();
  if (!savedState || typeof savedState !== "object") return;
  const savedLayers = Object.keys(savedState);
  if (savedLayers.length) state.layerControlsTouched = true;
  document.querySelectorAll("[data-layer]").forEach((input) => {
    if (Object.prototype.hasOwnProperty.call(savedState, input.dataset.layer)) {
      input.checked = Boolean(savedState[input.dataset.layer]);
    }
  });
}

function readLayerVisibilityState() {
  try {
    const parsed = JSON.parse(localStorage.getItem(LAYER_VISIBILITY_STORAGE_KEY) || "{}");
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

function saveLayerVisibilityState() {
  const visibility = {};
  document.querySelectorAll("[data-layer]").forEach((input) => {
    visibility[input.dataset.layer] = Boolean(input.checked);
  });
  localStorage.setItem(LAYER_VISIBILITY_STORAGE_KEY, JSON.stringify(visibility));
}

function initLayerLegendControls() {
  if (!dom.layerList) return;
  document.querySelectorAll("[data-layer-action]").forEach((button) => {
    button.addEventListener("click", () => {
      const action = button.dataset.layerAction;
      if (action === "show-all") setLayerInputs([...document.querySelectorAll("[data-layer]")], true);
      if (action === "hide-all") setLayerInputs([...document.querySelectorAll("[data-layer]")], false);
    });
  });
  syncLayerCardControls();
}

function initPanelSectionControls() {
  if (!dom.sidePanel) return;
  applySavedPanelSectionState();
  dom.sidePanel.querySelectorAll("[data-section-toggle]").forEach((button) => {
    button.addEventListener("click", () => {
      const section = button.closest("[data-panel-section]");
      setPanelSectionCollapsed(section, !section.classList.contains("panel-collapsed"));
    });
  });
  document.querySelectorAll("[data-panel-action]").forEach((button) => {
    button.addEventListener("click", () => {
      const collapsed = button.dataset.panelAction === "collapse-all";
      setAllPanelSectionsCollapsed(collapsed);
    });
  });
}

function setFramePanelCollapsed(collapsed, { skipRender = false, skipSave = false } = {}) {
  state.framePanelCollapsed = Boolean(collapsed);
  dom.frameDetectionBar?.classList.toggle("frame-panel-collapsed", state.framePanelCollapsed);
  if (dom.framePanelToggle) {
    dom.framePanelToggle.setAttribute("aria-expanded", state.framePanelCollapsed ? "false" : "true");
    dom.framePanelToggle.textContent = state.framePanelCollapsed ? "展开" : "收起";
    dom.framePanelToggle.title = state.framePanelCollapsed ? "展开图纸图层" : "收起图纸图层";
  }
  if (!skipRender && state.semantic) renderFrameDetection(state.semantic);
  if (!skipSave) saveFramePanelState();
}

function setFramePreviewCollapsed(collapsed, { skipSave = false } = {}) {
  state.framePreviewCollapsed = Boolean(collapsed);
  dom.frameDetectionBar?.classList.toggle("frame-preview-collapsed", state.framePreviewCollapsed);
  if (dom.framePreviewToggle) {
    dom.framePreviewToggle.setAttribute("aria-pressed", state.framePreviewCollapsed ? "true" : "false");
    dom.framePreviewToggle.textContent = state.framePreviewCollapsed ? "显示预览" : "隐藏预览";
    dom.framePreviewToggle.title = state.framePreviewCollapsed ? "显示图纸布局预览" : "隐藏图纸布局预览";
  }
  if (!skipSave) saveFramePanelState();
}

function setFramePanelHidden(hidden, { skipSave = false } = {}) {
  state.framePanelHidden = Boolean(hidden);
  dom.frameDetectionBar?.classList.toggle("hidden", state.framePanelHidden);
  dom.framePanelRestore?.classList.toggle("hidden", !state.framePanelHidden || !state.semantic);
  if (!skipSave) saveFramePanelState();
}

function saveFramePanelState() {
  localStorage.setItem(
    FRAME_PANEL_STATE_STORAGE_KEY,
    JSON.stringify({
      collapsed: state.framePanelCollapsed,
      previewCollapsed: state.framePreviewCollapsed,
      hidden: state.framePanelHidden,
    }),
  );
}

function applySavedPanelSectionState() {
  let savedState = {};
  try {
    savedState = JSON.parse(localStorage.getItem(PANEL_SECTION_STATE_STORAGE_KEY) || "{}");
  } catch {
    savedState = {};
  }
  dom.sidePanel.querySelectorAll("[data-panel-section]").forEach((section) => {
    const saved = savedState[section.dataset.panelSection];
    const collapsed = saved ? Boolean(saved.collapsed) : section.dataset.defaultCollapsed === "true";
    setPanelSectionCollapsed(section, collapsed, { skipSave: true });
  });
}

function savePanelSectionState() {
  if (!dom.sidePanel) return;
  const stateBySection = {};
  dom.sidePanel.querySelectorAll("[data-panel-section]").forEach((section) => {
    stateBySection[section.dataset.panelSection] = {
      collapsed: section.classList.contains("panel-collapsed"),
    };
  });
  localStorage.setItem(PANEL_SECTION_STATE_STORAGE_KEY, JSON.stringify(stateBySection));
}

function setAllPanelSectionsCollapsed(collapsed) {
  if (!dom.sidePanel) return;
  dom.sidePanel.querySelectorAll("[data-panel-section]").forEach((section) => setPanelSectionCollapsed(section, collapsed, { skipSave: true }));
  savePanelSectionState();
}

function setPanelSectionCollapsed(section, collapsed, { skipSave = false } = {}) {
  if (!section) return;
  section.classList.toggle("panel-collapsed", collapsed);
  const toggle = section.querySelector("[data-section-toggle]");
  if (toggle) {
    toggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
    const title = section.querySelector(".section-title")?.childNodes?.[0]?.textContent?.trim() || "面板";
    toggle.title = collapsed ? `展开${title}` : `折叠${title}`;
  }
  if (!skipSave) savePanelSectionState();
}

function setLayerInputs(inputs, checked, options = {}) {
  const markTouched = options.markTouched ?? true;
  const persist = options.persist ?? markTouched;
  if (markTouched) state.layerControlsTouched = true;
  inputs.forEach((input) => {
    input.checked = checked;
    scene.setLayerVisibility(input.dataset.layer, checked);
  });
  if (persist) saveLayerVisibilityState();
  syncLayerCardControls();
  renderStats(state.semantic || {});
}

function toggleLayerCard(card) {
  const input = card?.querySelector("[data-layer]");
  if (!input) return;
  setLayerInputs([input], !input.checked);
}

function syncLayerCardControls() {
  if (!dom.layerList) return;
  dom.layerList.querySelectorAll("[data-layer-card]").forEach((card) => {
    const input = card.querySelector("[data-layer]");
    card.classList.toggle("off", input && !input.checked);
    card.classList.toggle("active", input && input.checked);
    card.setAttribute("aria-pressed", input && input.checked ? "true" : "false");
  });
}

function renderDisplayMode(mode) {
  const adaptive = mode === "adaptive";
  dom.displayModeButton.textContent = adaptive ? "自适应省略" : "全量显示";
  dom.displayModeButton.setAttribute("aria-pressed", adaptive ? "true" : "false");
  dom.displayModeButton.title = adaptive
    ? "随视角距离隐藏普通标签，并弱化远处覆盖面"
    : "保持当前全量观察，不随视角自动省略";
}

function resetParseProgress() {
  state.progressPercent = 0;
  state.progressCompleted = false;
}

function setParseProgress(stageKey, summary = "", options = {}) {
  const stage = PARSE_PROGRESS_STAGES[stageKey] || PARSE_PROGRESS_STAGES.upload;
  if (state.progressHideTimer) {
    window.clearTimeout(state.progressHideTimer);
    state.progressHideTimer = null;
  }
  if (!dom.parseProgressPanel) return;
  const percent = Math.max(0, Math.min(100, Number(stage.percent) || 0));
  if (!options.allowRegression && state.progressCompleted && stageKey !== "complete" && stageKey !== "failed") {
    return;
  }
  if (!options.allowRegression && percent < state.progressPercent && stageKey !== "failed") {
    return;
  }
  state.progressPercent = percent;
  state.progressCompleted = stageKey === "complete" || stageKey === "failed";
  dom.parseProgressPanel.classList.remove("hidden", "complete", "failed");
  dom.parseProgressPanel.classList.toggle("complete", stageKey === "complete");
  dom.parseProgressPanel.classList.toggle("failed", stageKey === "failed");
  dom.parseProgressStage.textContent = stage.title;
  dom.parseProgressPercent.textContent = `${percent}%`;
  dom.parseProgressBar.style.width = `${percent}%`;
  dom.parseProgressSummary.textContent = summary || stage.title;
}

function completeParseProgress(summary) {
  setParseProgress("complete", summary || "解析完成，3D 预览已就绪");
  state.progressHideTimer = window.setTimeout(() => {
    dom.parseProgressPanel?.classList.add("hidden");
    state.progressHideTimer = null;
  }, 1800);
}

function failParseProgress(summary) {
  setParseProgress("failed", summary || "处理失败，请查看实时日志");
}

function syncProgressFromLog(line) {
  if (dom.parseProgressPanel?.classList.contains("hidden")) return;
  const message = String(line?.message || "");
  const level = String(line?.level || "").toUpperCase();
  if (!message) return;
  if (level === "ERROR" || /失败|不存在|未找到/.test(message)) {
    failParseProgress(message);
  } else if (/ezdxf|解析 DXF|读取 .*实体|图层 \[/.test(message)) {
    setParseProgress("dxf", message);
  } else if (/规则引擎|识别中/.test(message)) {
    setParseProgress("rules", message);
  } else if (/识别完成|清单校验|生成 semantic\.json|存档到/.test(message)) {
    setParseProgress("semantic", message);
  } else if (/Three\.js|3D 预览|场景构建/.test(message)) {
    setParseProgress("scene", message);
  }
}

async function refreshProjects({ autoLoadLatest = false, preferredProjectId = null, preferredDrawingId = null } = {}) {
  await projectManager.refresh(loadProject);
  if (preferredProjectId) {
    const preferredProject = projectManager.projects.find((project) => project.id === preferredProjectId);
    if (preferredProject) {
      await loadProject(preferredProject, { auto: true, drawingId: preferredDrawingId });
      return;
    }
    try {
      const project = await api.getProject(preferredProjectId);
      await loadProject(project, { auto: true, drawingId: preferredDrawingId });
      return;
    } catch {
      logger.add("ERROR", `分享链接中的项目不存在: ${preferredProjectId}`);
    }
  }
  if (autoLoadLatest && !state.semantic && projectManager.projects.length) {
    const latestProject = [...projectManager.projects].sort((left, right) => {
      const leftTime = new Date(left.updated_at || left.created_at || 0).getTime();
      const rightTime = new Date(right.updated_at || right.created_at || 0).getTime();
      return rightTime - leftTime;
    })[0];
    if (latestProject) {
      await loadProject(latestProject, { auto: true });
    }
  }
}

function snapshotLayerVisibility() {
  const visibility = {};
  document.querySelectorAll("[data-layer]").forEach((input) => {
    visibility[input.dataset.layer] = Boolean(input.checked);
  });
  return visibility;
}

function restoreLayerVisibility(visibility) {
  if (!visibility || typeof visibility !== "object") return;
  document.querySelectorAll("[data-layer]").forEach((input) => {
    const key = input.dataset.layer;
    if (!Object.prototype.hasOwnProperty.call(visibility, key)) return;
    input.checked = Boolean(visibility[key]);
    scene.setLayerVisibility(key, input.checked);
  });
  syncLayerCardControls();
}

function beginProjectSession(project) {
  if (state.project?.id && state.frameViewFilters && Object.keys(state.frameViewFilters).length) {
    state.frameViewFiltersByProject[state.project.id] = { ...state.frameViewFilters };
  }
  state.loadGeneration += 1;
  state.uploads = [];
  state.semantic = null;
  state.frameViewFilters = {};
  placement.reset();
  scene.resetGroups();
  scene.semantic = null;
  scene.mapper = null;
  if (dom.inspector) {
    dom.inspector.className = "inspector-empty";
    dom.inspector.textContent = "点击场景中的设备、区域或线路查看属性。";
  }
  if (dom.reviewList) dom.reviewList.innerHTML = `<div class="inspector-empty">暂无待审核条目。</div>`;
  if (dom.drawingList) dom.drawingList.innerHTML = "";
  projectManager.setActive(project?.id);
  return state.loadGeneration;
}

async function loadProject(project, { auto = false, drawingId = null } = {}) {
  const layerSnapshot = snapshotLayerVisibility();
  const generation = beginProjectSession(project);
  setProject(project, auto ? "auto" : "manual");
  try {
    const studio = await placement.ensureForProject(project);
    if (generation !== state.loadGeneration) return;
    if (studio) {
      const refreshed = await api.getProject(project.id);
      if (generation !== state.loadGeneration) return;
      setProject(refreshed, auto ? "auto" : "manual");
      project = refreshed;
    }
    const exported = await api.exportProject(project.id, { drawing_id: drawingId || project.current_drawing_id });
    if (generation !== state.loadGeneration) return;
    const currentDrawingId = drawingId || exported.current_drawing_id || exported.project?.current_drawing_id;
    const semantic = exported.schema_version
      ? exported
      : (exported.drawings || []).find((drawing) => drawing.project?.drawing_id === currentDrawingId) || exported.drawings?.[0];
    if (semantic) applySemantic(semantic, { updateProgress: false, preserveLayers: true });
    restoreLayerVisibility(layerSnapshot);
    logger.add("SUCCESS", `${auto ? "已自动加载最近项目" : "已加载项目"} ${project.name}`);
  } catch (error) {
    if (generation !== state.loadGeneration) return;
    logger.add("ERROR", `项目加载失败: ${error.message}`);
  }
}

function applyProjectData(exported, options = {}) {
  const currentDrawingId = exported.schema_version
    ? exported.project?.drawing_id
    : exported.current_drawing_id || exported.project?.current_drawing_id;
  const semantic = exported.schema_version
    ? exported
    : (exported.drawings || []).find((drawing) => drawing.project?.drawing_id === currentDrawingId) || exported.drawings?.[0];
  if (semantic) applySemantic(semantic, { updateProgress: false });
  const project = exported.project || semantic?.project;
  if (project?.id) {
    setProject(project, options.source || "manual");
  }
}

async function uploadFiles(files) {
  if (!files.length) return;
  hideUploadParsePrompt();
  ensureDefaultSiteProfiles();
  dom.uploadButton.disabled = true;
  resetParseProgress();
  setParseProgress("upload", `准备上传 ${files.length} 个文件`);
  try {
    for (const [index, file] of files.entries()) {
      setParseProgress("upload", `上传 ${index + 1}/${files.length}: ${file.name}`);
      logger.add("INFO", `上传 ${file.name}`);
      const result = await api.upload(file);
      state.uploads.push(result);
      logger.add("SUCCESS", result.message || `${file.name} 已上传`);
    }
    renderDrawingList();
    dom.parseButton.disabled = state.uploads.length === 0;
    setParseProgress("upload", "上传完成，正在自动解析");
    logger.add("INFO", "上传完成，开始自动解析并生成 3D");
    await parseUploads();
  } catch (error) {
    failParseProgress(`上传失败: ${error.message}`);
    logger.add("ERROR", `上传失败: ${error.message}`);
  } finally {
    dom.uploadButton.disabled = false;
    dom.fileInput.value = "";
  }
}

async function parseUploads() {
  if (!state.uploads.length) return;
  hideUploadParsePrompt();
  const selected = await ensureSiteProfilesSelected();
  if (!selected) return;
  let batchProject = await ensureWritableProjectSelected(defaultProjectName());
  if (!batchProject) return;
  const siteProfiles = currentSiteProfiles();
  if (isCurrentProjectArchived()) {
    logger.add("ERROR", "当前项目已归档，只能只读查看；请恢复或新建项目后再解析");
    return;
  }
  logger.add("INFO", `本批 ${state.uploads.length} 张图纸将写入同一项目: ${batchProject.name}（${siteProfiles.map(profileDisplayName).join(" + ")}）`);

  dom.parseButton.disabled = true;
  resetParseProgress();
  try {
    for (const [index, upload] of state.uploads.entries()) {
      setParseProgress("dxf", `解析 ${index + 1}/${state.uploads.length}: ${upload.original_name}`);
      logger.add("INFO", `开始解析 ${upload.original_name}`);
      const semantic = await api.parse({
        file_id: upload.file_id,
        project_id: batchProject.id,
        save_dir: batchProject.save_dir,
        site_profiles: siteProfiles,
      });
      applySemantic(semantic, { updateProgress: true });
      batchProject = state.project || batchProject;
      logger.add("SUCCESS", `${upload.original_name} 解析完成`);
      await autoCaptureVisualAudit(semantic);
    }
    state.uploads = [];
    renderDrawingList();
    await refreshProjects();
    completeParseProgress("全部图纸解析完成");
  } catch (error) {
    failParseProgress(`解析失败: ${error.message}`);
    logger.add("ERROR", `解析失败: ${error.message}`);
  } finally {
    dom.parseButton.disabled = state.uploads.length === 0 || isCurrentProjectArchived();
  }
}

function showUploadParsePrompt() {
  if (!dom.uploadParsePrompt || !state.uploads.length || isCurrentProjectArchived()) return;
  const count = state.uploads.length;
  const projectName = state.project?.name || "当前项目";
  if (dom.uploadParsePromptSummary) {
    dom.uploadParsePromptSummary.textContent = `${projectName} 已上传 ${count} 张图纸，是否立即解析生成 3D 模型？`;
  }
  dom.uploadParsePrompt.classList.remove("hidden");
  window.clearTimeout(state.parsePromptTimer);
  state.parsePromptTimer = window.setTimeout(() => hideUploadParsePrompt(), UPLOAD_PARSE_PROMPT_TIMEOUT_MS);
}

function hideUploadParsePrompt() {
  window.clearTimeout(state.parsePromptTimer);
  state.parsePromptTimer = null;
  dom.uploadParsePrompt?.classList.add("hidden");
}

function applySemantic(semantic, options = {}) {
  state.semantic = semantic;
  if (Array.isArray(semantic.site_profiles) && semantic.site_profiles.length) {
    state.siteProfiles = semantic.site_profiles;
    renderSiteProfileSummary();
  }
  if (options.updateProgress) {
    setParseProgress("scene", "正在构建 3D 场景");
  }
  applyScenePerformanceProfile(semantic);
  initializeFrameViewFilters(semantic);
  loadSemanticForFrameViews({ preserveView: Boolean(options.preserveView) });
  dom.dropHint.classList.add("hidden");
  renderFrameDetection(semantic);
  renderStats(semantic);
  renderProjectNotes(semantic);
  if (semantic.project) {
    setProject(
      {
        id: semantic.project.id,
        name: semantic.project.name,
        save_dir: semantic.project.save_dir,
        status: semantic.project.status || "active",
        site_profiles: semantic.project.site_profiles || semantic.site_profiles || state.siteProfiles,
        drawings: semantic.project.drawings || [],
        current_drawing_id: semantic.project.current_drawing_id || semantic.project.drawing_id,
      },
      state.projectSource === "auto" ? "auto" : "parsed",
    );
  }
  syncProjectActionButtons();
}

function initializeFrameViewFilters(semantic) {
  const frames = semanticFrames(semantic);
  const projectId = semantic?.project?.id || state.project?.id || "";
  const memory = projectId ? state.frameViewFiltersByProject[projectId] : null;
  const filters = {};
  frames.forEach((frame) => {
    const key = frameViewKey(frame);
    if (!key) return;
    filters[key] = memory && Object.prototype.hasOwnProperty.call(memory, key) ? Boolean(memory[key]) : true;
  });
  if (!Object.keys(filters).length) filters.main_plan = memory?.main_plan !== false;
  state.frameViewFilters = filters;
  if (projectId) state.frameViewFiltersByProject[projectId] = { ...filters };
}

function hasRenderableCoverage(device) {
  if (!device?.coverage) return false;
  if (device.coverage.disabled || device.attributes?.coverage_disabled) return false;
  return Boolean(device.coverage.length_m || device.coverage.radius_m);
}

function loadSemanticForFrameViews(options = {}) {
  if (!state.semantic) return;
  const filtered = filterSemanticByFrameViews(state.semantic);
  scene.loadSemantic(filtered, options);
}

function applyScenePerformanceProfile(semantic) {
  const project = semantic?.project || {};
  const profileKey = `${project.id || ""}:${project.drawing_id || project.current_drawing_id || ""}`;
  const counts = {
    devices: (semantic.devices || []).length,
    structures: (semantic.structures || []).length,
    parking: (semantic.parking_spaces || []).length,
    fixtures: (semantic.fixtures || []).length,
    areas: (semantic.areas || []).length,
    cables: (semantic.cables || []).length,
  };
  const coverageCount = (semantic.devices || []).filter((device) => {
    const type = String(device.type || "");
    return (type === "network.ap" || type.startsWith("security.camera")) && hasRenderableCoverage(device);
  }).length;
  const score =
    counts.devices * 1.2
    + counts.structures * 0.35
    + counts.parking * 2
    + counts.fixtures * 1.8
    + counts.cables * 0.8
    + coverageCount * 1.5
    + counts.areas * 1.5;
  const heavy =
    counts.devices >= PERFORMANCE_DEVICE_THRESHOLD
    || counts.structures >= PERFORMANCE_STRUCTURE_THRESHOLD
    || score >= PERFORMANCE_SCORE_THRESHOLD;

  const hasSavedDisplayMode = localStorage.getItem(DISPLAY_MODE_STORAGE_KEY) === "full" || localStorage.getItem(DISPLAY_MODE_STORAGE_KEY) === "adaptive";
  if (heavy && scene.getDetailMode() !== "adaptive" && !hasSavedDisplayMode) {
    scene.setDetailMode("adaptive");
    renderDisplayMode("adaptive");
  }
  if (!heavy || state.layerControlsTouched || state.performanceProfileKey === profileKey) return;

  const inputs = AUTO_PERFORMANCE_LAYER_OFF
    .map((layer) => document.querySelector(`[data-layer="${layer}"]`))
    .filter(Boolean);
  setLayerInputs(inputs, false, { markTouched: false });
  state.performanceProfileKey = profileKey;
  logger.add("INFO", "大体量图纸已自动启用流畅模式：覆盖层默认关闭，左侧可随时打开。");
}

function filterSemanticByFrameViews(semantic) {
  const enabled = new Set(
    Object.entries(state.frameViewFilters)
      .filter(([, active]) => active)
      .map(([key]) => key),
  );
  const hasFilters = Object.keys(state.frameViewFilters).length > 0;
  const clone = { ...semantic };
  ["structures", "annotations"].forEach((key) => {
    if (!Array.isArray(semantic[key])) return;
    clone[key] = semantic[key].filter((item) => !hasFilters || enabled.has(itemFrameViewKey(item, key)));
  });
  clone.frame_view_filters = { ...state.frameViewFilters };
  return clone;
}

function itemFrameViewKey(item, collectionKey = "") {
  const attrs = item?.attributes || {};
  const merged = attrs.merged_from_system_view;
  if (merged) return String(merged);
  const sourceKind = String(attrs.source_kind || "");
  const layerRole = String(attrs.layer_role || "");
  const layer = String(item?.original_layer || item?.layer || "");
  const type = String(item?.type || "");
  if (sourceKind.includes("cabinet_link") || layer.includes("机柜链路")) return "cabinet_link";
  if (
    sourceKind.includes("cabinet_power")
    || sourceKind.includes("spotlight_power")
    || layerRole === "cabinet_cable"
    || layerRole === "spotlight_cable"
    || type.includes("spotlight")
    || type === "lighting.floodlight"
    || layer.includes("机柜&射灯")
    || layer.includes("机柜射灯")
  ) {
    return "cabinet_spotlight_power";
  }
  if (sourceKind.includes("tail_camera") || type.startsWith("security.camera")) return "monitor";
  if (type === "network.ap" || layer.includes("网络&广播") || layer.includes("网络广播")) return "network_broadcast";
  if (type === "network.cabinet") return "cabinet_link";
  if (collectionKey === "parking_spaces") return "main_plan";
  return "main_plan";
}

function semanticFrames(semantic) {
  if (!semantic) return [];
  if (Array.isArray(semantic.frames)) return semantic.frames;
  if (Array.isArray(semantic.quality?.frame_detection?.frames)) return semantic.quality.frame_detection.frames;
  return [];
}

function frameViewKey(frame) {
  if (!frame) return "";
  if (frame.reference_only || frame.kind === "reference_plan") return "reference_plan";
  if (frame.kind === "main_plan") return "main_plan";
  return frame.system_view_kind || frame.kind || frame.frame_id || "";
}

function setProject(project, source = "manual") {
  state.project = project;
  state.projectSource = source;
  projectManager.setActive(project?.id);
  dom.projectTitle.textContent = project.name || "CAD 弱电图纸 3D 预览";
  if (Array.isArray(project.site_profiles) && project.site_profiles.length) {
    state.siteProfiles = project.site_profiles;
    renderSiteProfileSummary();
  }
  const statusLabel = project.status === "archived" ? " · 已归档，只读" : "";
  dom.projectSubtitle.textContent = `${project.save_dir || "本地项目库"}${statusLabel}`;
  syncProjectUrl(project);
  if (source !== "auto" && !reverseValidationMode) saveLastProjectSelection(project);
  syncProjectActionButtons();
}

function syncProjectUrl(project) {
  if (!project?.id || !window.history?.replaceState) return;
  const params = new URLSearchParams(window.location.search);
  params.set("project", project.id);
  const semanticProject = state.semantic?.project;
  const semanticDrawingId = semanticProject?.id === project.id ? semanticProject.drawing_id : null;
  const drawingId = project.current_drawing_id || semanticDrawingId || null;
  if (drawingId) {
    params.set("drawing", drawingId);
  } else {
    params.delete("drawing");
  }
  const nextUrl = `${window.location.pathname}?${params.toString()}${window.location.hash || ""}`;
  window.history.replaceState({}, "", nextUrl);
}

async function exportStaticPreview() {
  const projectId = state.semantic?.project?.id || state.project?.id;
  if (!projectId) {
    logger.add("ERROR", "请先加载或解析一个项目后再导出静态 HTML");
    return;
  }
  const drawingId = state.semantic?.project?.drawing_id || state.project?.current_drawing_id || null;
  let fileName = defaultStaticExportFileName();
  let saveHandle = null;
  try {
    if (canUseSaveFilePicker()) {
      saveHandle = await window.showSaveFilePicker({
        suggestedName: fileName,
        types: [
          {
            description: "HTML 文件",
            accept: { "text/html": [STATIC_EXPORT_EXTENSION] },
          },
        ],
      });
      fileName = normalizeStaticExportFileName(saveHandle.name || fileName);
    } else {
      const promptedName = window.prompt("请输入导出文件名", fileName);
      if (promptedName === null) return;
      fileName = normalizeStaticExportFileName(promptedName);
      if (!fileName) {
        logger.add("ERROR", "静态导出文件名不能为空");
        return;
      }
    }
    dom.staticExportButton.disabled = true;
    logger.add("INFO", "正在导出独立静态 HTML 预览");
    const result = await api.exportStaticProject(projectId, { drawing_id: drawingId, file_name: fileName });
    if (Number(result.size_bytes) <= 0) {
      throw new Error("服务端生成的静态 HTML 为空，已停止写入本地文件");
    }
    if (saveHandle) {
      const savedBytes = await saveStaticExportFile(saveHandle, result.url);
      logger.add("SUCCESS", `静态 HTML 已保存: ${result.file_name || fileName} (${formatBytes(savedBytes)})`);
      return;
    }
    downloadStaticExport(result.url, result.file_name || fileName);
    logger.add("SUCCESS", `静态 HTML 已生成: ${result.path} (${formatBytes(result.size_bytes)})`);
  } catch (error) {
    if (error.name === "AbortError") return;
    logger.add("ERROR", `静态导出失败: ${error.message}`);
  } finally {
    syncProjectActionButtons();
  }
}

async function reparseCurrentProject(event) {
  event?.preventDefault();
  const projectId = state.semantic?.project?.id || state.project?.id;
  if (!projectId) {
    logger.add("ERROR", "请先加载或解析一个项目后再重解析");
    return;
  }
  if (isCurrentProjectArchived()) {
    logger.add("ERROR", "当前项目已归档，只能只读查看；请恢复后再重解析");
    return;
  }
  let bbox = null;
  try {
    bbox = parseManualBbox(dom.bboxInput?.value || "");
  } catch (error) {
    logger.add("ERROR", error.message);
    return;
  }
  const drawingId = state.semantic?.project?.drawing_id || state.project?.current_drawing_id || null;
  const payload = {
    drawing_id: drawingId,
    site_profiles: currentSiteProfiles(),
    force_main_frame: bbox ? { kind: "manual", bbox } : false,
  };
  dom.reparseButton.disabled = true;
  resetParseProgress();
  setParseProgress("dxf", bbox ? "按手动 bbox 重新解析图纸" : "按自动图框规则重新解析图纸");
  try {
    logger.add("INFO", bbox ? `按 bbox 重解析: ${formatBbox(bbox)}` : "请求后端按当前图框规则重解析");
    const result = await api.reparseProject(projectId, payload);
    setParseProgress("scene", "正在刷新 3D 场景");
    applyReparseResult(result);
    await refreshProjects();
    completeParseProgress("重解析完成");
    logger.add("SUCCESS", "重解析完成");
  } catch (error) {
    failParseProgress(`重解析失败: ${error.message}`);
    logger.add("ERROR", `重解析失败: ${error.message}`);
  } finally {
    syncProjectActionButtons();
  }
}

function applyReparseResult(result) {
  const semantic = result?.semantic || result;
  if (semantic?.schema_version || semantic?.stats || Array.isArray(semantic?.devices)) {
    applySemantic(semantic, { updateProgress: false });
    return;
  }
  applyProjectData(result, { source: "manual" });
}

function parseManualBbox(value) {
  const text = String(value || "").trim();
  if (!text) return null;
  let parsed = null;
  if (text.startsWith("{") || text.startsWith("[")) {
    try {
      parsed = JSON.parse(text);
    } catch {
      throw new Error("bbox JSON 格式错误，请输入 min_x,min_y,max_x,max_y");
    }
  }
  if (Array.isArray(parsed)) {
    if (parsed.length !== 4) throw new Error("bbox 数组需要 4 个数字: min_x,min_y,max_x,max_y");
    parsed = { min_x: parsed[0], min_y: parsed[1], max_x: parsed[2], max_y: parsed[3] };
  }
  const bbox = parsed && typeof parsed === "object"
    ? {
        min_x: Number(parsed.min_x ?? parsed.minX),
        min_y: Number(parsed.min_y ?? parsed.minY),
        max_x: Number(parsed.max_x ?? parsed.maxX),
        max_y: Number(parsed.max_y ?? parsed.maxY),
      }
    : bboxFromText(text);
  if (!bbox || !Object.values(bbox).every(Number.isFinite)) {
    throw new Error("bbox 格式错误，请输入 min_x,min_y,max_x,max_y");
  }
  if (bbox.max_x <= bbox.min_x || bbox.max_y <= bbox.min_y) {
    throw new Error("bbox 范围错误，max_x/max_y 必须大于 min_x/min_y");
  }
  return bbox;
}

function bboxFromText(text) {
  const values = text.split(/[,\s，]+/).map((item) => Number(item.trim())).filter((item) => Number.isFinite(item));
  if (values.length !== 4) return null;
  return { min_x: values[0], min_y: values[1], max_x: values[2], max_y: values[3] };
}

async function captureVisualAudit() {
  const projectId = state.semantic?.project?.id || state.project?.id;
  if (!projectId) {
    logger.add("ERROR", "请先加载或解析一个项目后再生成审计截图");
    return;
  }
  const drawingId = state.semantic?.project?.drawing_id || state.project?.current_drawing_id || null;
  dom.visualAuditButton.disabled = true;
  try {
    logger.add("INFO", "正在生成系统模块 CAD 截图");
    const result = await api.captureVisualAudit(projectId, { drawing_id: drawingId, force: true });
    logger.add("SUCCESS", `已生成 ${result.captured?.length || 0} 张审计截图`);
    const refreshed = await api.exportProject(projectId, { drawing_id: drawingId });
    applyProjectData(refreshed, { source: "manual" });
  } catch (error) {
    logger.add("ERROR", `审计截图生成失败: ${error.message}`);
  } finally {
    syncProjectActionButtons();
  }
}

async function autoCaptureVisualAudit(semantic) {
  const visual = semantic?.quality?.visual_audit || {};
  if (!visual.requires_screenshot_capture || !semantic?.project?.id) return;
  try {
    setParseProgress("audit", "正在生成系统模块审计截图");
    logger.add("INFO", "解析结果包含系统模块截图审计，正在自动生成 CAD 截图");
    const result = await api.captureVisualAudit(semantic.project.id, {
      drawing_id: semantic.project.drawing_id,
      force: false,
    });
    logger.add("SUCCESS", `系统模块审计截图已生成 ${result.captured?.length || 0} 张`);
    const refreshed = await api.exportProject(semantic.project.id, { drawing_id: semantic.project.drawing_id });
    applyProjectData(refreshed, { source: "parsed" });
  } catch (error) {
    logger.add("WARNING", `系统模块截图自动生成失败，可稍后点击“生成审计截图”重试: ${error.message}`);
  }
}

async function copyProjectShareLink() {
  const projectId = state.semantic?.project?.id || state.project?.id;
  if (!projectId) {
    logger.add("ERROR", "请先加载或解析一个项目后再复制分享链接");
    return;
  }
  const drawingId = state.semantic?.project?.drawing_id || state.project?.current_drawing_id || null;
  dom.shareLinkButton.disabled = true;
  try {
    logger.add("INFO", "正在生成包含最新数据的静态分享页面");
    const result = await api.shareProjectLink(projectId, drawingId);
    const shareUrl = normalizeShareUrl(result.url);
    await copyText(shareUrl);
    logger.add("SUCCESS", `已复制内网静态分享链接: ${shareUrl}`);
    const networkCheck = buildWindowsNetworkCheckCommand(shareUrl);
    if (networkCheck) {
      logger.add("INFO", `Windows 端仍无法访问时，请执行: ${networkCheck}。如果 TcpTestSucceeded: False，就是网络隔离或端口被拦截。`);
    }
  } catch (error) {
    logger.add("ERROR", `复制分享链接失败: ${error.message}`);
  } finally {
    syncProjectActionButtons();
  }
}

async function openProjectDirectory() {
  const projectId = state.semantic?.project?.id || state.project?.id;
  if (!projectId) {
    logger.add("ERROR", "请先加载一个项目后再打开项目目录");
    return;
  }
  try {
    const result = await api.openProjectFolder(projectId);
    logger.add("SUCCESS", `已打开项目目录: ${result.path}`);
  } catch (error) {
    logger.add("ERROR", `打开项目目录失败: ${error.message}`);
  }
}

async function openCurrentSourceFile() {
  const projectId = state.semantic?.project?.id || state.project?.id;
  if (!projectId) {
    logger.add("ERROR", "请先加载一个项目后再打开源 DWG/DXF");
    return;
  }
  const drawingId = state.semantic?.project?.drawing_id || state.project?.current_drawing_id || null;
  try {
    const result = await api.openProjectSourceFile(projectId, drawingId);
    logger.add("SUCCESS", `已打开源图纸: ${result.path}`);
  } catch (error) {
    logger.add("ERROR", `打开源图纸失败: ${error.message}`);
  }
}

function syncProjectActionButtons() {
  const hasProject = Boolean(state.semantic?.project?.id || state.project?.id);
  const archived = isCurrentProjectArchived();
  if (dom.visualAuditButton) dom.visualAuditButton.disabled = !hasProject || archived;
  if (dom.staticExportButton) dom.staticExportButton.disabled = !hasProject || archived;
  if (dom.shareLinkButton) dom.shareLinkButton.disabled = !hasProject || archived;
  if (dom.openProjectDirButton) dom.openProjectDirButton.disabled = !hasProject;
  if (dom.openSourceFileButton) dom.openSourceFileButton.disabled = !hasProject;
  if (dom.reparseButton) dom.reparseButton.disabled = !hasProject || archived;
  if (dom.parseButton) dom.parseButton.disabled = state.uploads.length === 0 || archived;
}

function isCurrentProjectArchived() {
  return state.project?.status === "archived" || state.semantic?.project?.status === "archived";
}

function handleProjectMutation(project, action) {
  const currentId = state.project?.id || state.semantic?.project?.id;
  if (project?.id !== currentId) return;
  if (action === "archive") {
    state.project = { ...state.project, status: "archived" };
  } else if (action === "restore") {
    state.project = { ...state.project, status: "active" };
  } else if (action === "delete") {
    state.project = null;
    state.semantic = null;
    renderFrameDetection(null);
    dom.projectTitle.textContent = "CAD 弱电图纸 3D 预览";
    dom.projectSubtitle.textContent = "上传 DWG/DXF，解析语义对象并生成 Three.js 交互模型";
  }
  syncProjectActionButtons();
}

function ensureDefaultSiteProfiles() {
  if (Array.isArray(state.siteProfiles) && state.siteProfiles.length) return state.siteProfiles;
  state.siteProfiles = ["generic"];
  renderSiteProfileSummary();
  return state.siteProfiles;
}

function currentSiteProfiles() {
  return [...ensureDefaultSiteProfiles()];
}

async function ensureSiteProfilesSelected({ forceModal = false } = {}) {
  ensureDefaultSiteProfiles();
  if (!forceModal && state.siteProfiles.length) return true;
  return openSiteProfileModal();
}

function openSiteProfileModal() {
  if (!dom.siteProfileModal) return Promise.resolve(true);
  const selected = ensureDefaultSiteProfiles();
  if (dom.siteProfileGeneric) dom.siteProfileGeneric.checked = selected.includes("generic");
  if (dom.siteProfileExpress) dom.siteProfileExpress.checked = selected.includes("express");
  if (dom.siteProfileSupplyChain) dom.siteProfileSupplyChain.checked = selected.includes("supply_chain");
  dom.siteProfileModal.classList.add("open");
  return new Promise((resolve) => {
    state.siteProfileResolve = resolve;
  });
}

function confirmSiteProfiles() {
  const selected = [];
  if (dom.siteProfileGeneric?.checked) selected.push("generic");
  if (dom.siteProfileExpress?.checked) selected.push("express");
  if (dom.siteProfileSupplyChain?.checked) selected.push("supply_chain");
  if (!selected.length) {
    logger.add("ERROR", "请至少选择一个场地类型 profile");
    return;
  }
  state.siteProfiles = selected;
  state.siteProfilesExplicit = true;
  renderSiteProfileSummary();
  closeSiteProfileModal(true);
}

function closeSiteProfileModal(result) {
  dom.siteProfileModal?.classList.remove("open");
  state.siteProfileResolve?.(result);
  state.siteProfileResolve = null;
}

function renderSiteProfileSummary() {
  if (!dom.siteProfileSummary) return;
  dom.siteProfileSummary.textContent = `场地: ${state.siteProfiles.map(profileDisplayName).join(" + ")}`;
}

function renderReverseValidationLanding() {
  dom.projectTitle.textContent = "反推规则验证模式";
  dom.projectSubtitle.textContent = "不会自动加载历史项目；上传或选择图纸后使用当前统一读取规则解析";
  logger.add("INFO", "已进入反推规则验证模式，不自动加载浏览器记录中的历史项目");
}

async function createReverseValidationProject(defaultName = defaultProjectName()) {
  const name = buildReverseValidationProjectName(defaultName);
  try {
    logger.add("INFO", `正在创建独立验证项目: ${name}`);
    const project = await api.createProject({ name, save_dir: null, site_profiles: currentSiteProfiles() });
    setProject(project, "validation");
    await projectManager.refresh(loadProject);
    logger.add("SUCCESS", `已创建独立验证项目 ${project.name}`);
    return project;
  } catch (error) {
    logger.add("ERROR", `独立验证项目创建失败: ${error.message}`);
    return null;
  }
}

function buildReverseValidationProjectName(defaultName = defaultProjectName()) {
  const base = String(defaultName || "新图纸").replace(/\s+/g, " ").trim() || "新图纸";
  const now = new Date();
  const stamp = [
    now.getFullYear(),
    String(now.getMonth() + 1).padStart(2, "0"),
    String(now.getDate()).padStart(2, "0"),
    String(now.getHours()).padStart(2, "0"),
    String(now.getMinutes()).padStart(2, "0"),
  ].join("");
  return `${base}-反推规则验证-${stamp}`;
}

function profileDisplayName(profile) {
  return {
    generic: "通用",
    express: "快运",
    supply_chain: "供应链",
  }[profile] || profile;
}

function normalizeShareUrl(url) {
  const shareHost = getConfiguredShareHost();
  if (!shareHost) return url;
  try {
    const parsed = new URL(url, window.location.origin);
    if (isLocalShareHost(parsed.hostname)) {
      parsed.hostname = shareHost;
      if (!parsed.port && window.location.port) parsed.port = window.location.port;
      return parsed.href;
    }
  } catch {
    return url;
  }
  return url;
}

function getConfiguredShareHost() {
  const share = window.CAD3D_SHARE || {};
  const candidates = [share.host, ...(Array.isArray(share.hosts) ? share.hosts : [])];
  return candidates.map((host) => String(host || "").trim()).find((host) => host && !isLocalShareHost(host)) || "";
}

function isLocalShareHost(host) {
  return LOCAL_SHARE_HOSTS.has(String(host || "").trim().toLowerCase());
}

function buildWindowsNetworkCheckCommand(url) {
  try {
    const parsed = new URL(url, window.location.origin);
    const host = parsed.hostname;
    const port = parsed.port || (parsed.protocol === "https:" ? "443" : "80");
    if (!host || isLocalShareHost(host)) return "";
    return `Test-NetConnection ${host} -Port ${port}`;
  } catch {
    return "";
  }
}

async function copyText(text) {
  if (navigator.clipboard?.writeText && window.isSecureContext) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.left = "-9999px";
  document.body.appendChild(textarea);
  textarea.select();
  const copied = document.execCommand("copy");
  textarea.remove();
  if (!copied) throw new Error("浏览器阻止了复制，请手动复制日志中的链接");
}

function canUseSaveFilePicker() {
  return typeof window.showSaveFilePicker === "function" && window.isSecureContext;
}

async function saveStaticExportFile(saveHandle, url) {
  const blob = await api.download(url);
  if (!blob || blob.size <= 0) {
    throw new Error("下载到的静态 HTML 为空，已停止写入本地文件");
  }
  const writable = await saveHandle.createWritable();
  let didWrite = false;
  try {
    await writable.write(await blob.arrayBuffer());
    didWrite = true;
  } finally {
    if (didWrite) {
      await writable.close();
    } else if (typeof writable.abort === "function") {
      await writable.abort();
    }
  }
  return blob.size;
}

function downloadStaticExport(url, fileName) {
  const link = document.createElement("a");
  link.href = new URL(url, window.location.origin).href;
  link.download = fileName;
  link.rel = "noopener";
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.open(link.href, "_blank", "noopener");
}

function formatBytes(value) {
  const bytes = Number(value);
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 KB";
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function defaultStaticExportFileName() {
  const project = state.semantic?.project || state.project || {};
  const drawing = state.semantic?.drawing_meta || {};
  const name = project.drawing_name || drawing.original_name || project.name || "cad-static-preview";
  return normalizeStaticExportFileName(name);
}

function normalizeStaticExportFileName(value) {
  const cleaned = String(value || "")
    .replace(/\.(dwg|dxf|html?)$/i, "")
    .replace(/[<>:"/\\|?*\x00-\x1f]/g, "_")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/[. ]+$/g, "");
  return cleaned ? `${cleaned}${STATIC_EXPORT_EXTENSION}` : "";
}

function getInitialProjectTarget() {
  const params = new URLSearchParams(window.location.search);
  const projectId = params.get("project");
  if (projectId) {
    return {
      projectId,
      drawingId: params.get("drawing") || null,
      scoped: params.get("scope") === "project" || params.get("singleProject") === "1",
    };
  }
  if (isReverseValidationMode()) return null;
  return getLastProjectSelection();
}

function isReverseValidationMode() {
  const params = new URLSearchParams(window.location.search);
  return (
    params.get("mode") === "reverse-validation"
    || params.get("validation") === "reverse"
    || params.get("fresh") === "1"
  );
}

function saveLastProjectSelection(project) {
  if (!project?.id) return;
  localStorage.setItem(
    LAST_PROJECT_STORAGE_KEY,
    JSON.stringify({
      projectId: project.id,
      drawingId: project.current_drawing_id || state.semantic?.project?.drawing_id || null,
    }),
  );
}

function getLastProjectSelection() {
  const saved = readStorageObject(LAST_PROJECT_STORAGE_KEY);
  return saved?.projectId ? { projectId: saved.projectId, drawingId: saved.drawingId || null } : null;
}

function readStorageObject(key) {
  try {
    const parsed = JSON.parse(localStorage.getItem(key) || "null");
    return parsed && typeof parsed === "object" ? parsed : null;
  } catch {
    return null;
  }
}

async function ensureWritableProjectSelected(defaultName = defaultProjectName()) {
  if (state.project && state.projectSource !== "auto" && !isCurrentProjectArchived()) {
    return state.project;
  }
  if (
    initialProjectTarget?.scoped
    && state.project?.id === initialProjectTarget.projectId
    && !isCurrentProjectArchived()
  ) {
    return state.project;
  }
  if (reverseValidationMode && !initialProjectTarget) {
    return createReverseValidationProject(defaultName);
  }
  if (isCurrentProjectArchived()) {
    logger.add("WARNING", "当前项目已归档，将新建项目后再解析");
  } else if (state.projectSource === "auto") {
    logger.add("INFO", "当前是自动加载的历史项目，将新建项目以免写入历史图纸");
  } else {
    logger.add("INFO", "未选择项目，将按图纸名自动创建项目");
  }
  return createUploadTargetProject(defaultName);
}

function siteProfilesForNewProject() {
  if (state.siteProfilesExplicit && state.siteProfiles.length) {
    return [...state.siteProfiles];
  }
  state.siteProfiles = ["generic"];
  renderSiteProfileSummary();
  return ["generic"];
}

async function createUploadTargetProject(defaultName = defaultProjectName()) {
  const name = String(defaultName || "未命名弱电项目").replace(/\s+/g, " ").trim() || "未命名弱电项目";
  const siteProfiles = siteProfilesForNewProject();
  try {
    logger.add("INFO", `正在创建项目: ${name}`);
    const project = await api.createProject({ name, save_dir: null, site_profiles: siteProfiles });
    setProject(project, "created");
    await projectManager.refresh(loadProject);
    logger.add("SUCCESS", `已创建项目 ${project.name}`);
    return project;
  } catch (error) {
    logger.add("ERROR", `项目创建失败: ${error.message}`);
    return null;
  }
}

function defaultProjectNameForFiles(files) {
  const first = files?.[0]?.name;
  return first ? first.replace(/\.(dwg|dxf)$/i, "") : defaultProjectName();
}

function defaultProjectName() {
  const first = state.uploads[0]?.original_name;
  return first ? first.replace(/\.(dwg|dxf)$/i, "") : "未命名弱电项目";
}

function renderDrawingList() {
  if (!state.uploads.length) {
    dom.drawingList.innerHTML = `<div class="drawing-item"><strong>暂无图纸</strong><span>支持多文件上传</span></div>`;
    return;
  }
  dom.drawingList.innerHTML = state.uploads
    .map((upload) => `<div class="drawing-item"><strong>${escapeHtml(upload.original_name)}</strong><span>${upload.format.toUpperCase()} · ${upload.converted ? "已转换" : "可直接解析"}</span></div>`)
    .join("");
}

function renderStats(semantic) {
  const stats = semantic.stats || {};
  const devices = semantic.devices || [];
  const cameras = devices.filter((device) => String(device.type).startsWith("security.camera")).length;
  const aps = devices.filter((device) => device.type === "network.ap").length;
  const selectedStats = layerScopedStats(semantic);
  if (selectedStats.length) {
    renderStatSlots(
      [dom.stats.devices, dom.stats.cables, dom.stats.cameras, dom.stats.entities],
      selectedStats.slice(0, 4),
      "status",
    );
    renderStatSlots(
      [dom.stats.metricDevices, dom.stats.metricCameras, dom.stats.metricAps, dom.stats.metricReview],
      selectedStats.slice(0, 4),
      "metric",
    );
  } else {
    setStatusSlot(dom.stats.devices, stats.devices || 0, "设备");
    setStatusSlot(dom.stats.cables, stats.cables || 0, "线路");
    setStatusSlot(dom.stats.cameras, cameras, "摄像头");
    setStatusSlot(dom.stats.entities, stats.total_entities || 0, "实体");
    setMetricSlot(dom.stats.metricDevices, stats.devices || 0, "设备");
    setMetricSlot(dom.stats.metricCameras, cameras, "摄像头");
    setMetricSlot(dom.stats.metricAps, aps, "AP");
    setMetricSlot(dom.stats.metricReview, stats.review_needed || 0, "待审核");
  }
  renderReviewList(semantic);
}

function layerScopedStats(semantic) {
  if (!state.layerControlsTouched) return [];
  const inputs = [...document.querySelectorAll("[data-layer]")];
  if (!inputs.length) return [];
  const checkedLayers = new Set(inputs.filter((input) => input.checked).map((input) => input.dataset.layer));
  if (!checkedLayers.size || checkedLayers.size === inputs.length) return [];
  const devices = semantic.devices || [];
  const cables = semantic.cables || [];
  const fixtures = semantic.fixtures || [];
  const parkingSpaces = semantic.parking_spaces || [];
  const structures = semantic.structures || [];
  const areas = semantic.areas || [];
  const cameraWithCoverage = hasRenderableCoverage;
  const wallBulletCamera = (device) => device.type === "security.camera.bullet";
  const rearCamera = (device) => device.type === "security.camera.rear";
  const layerStats = new Map([
    ["shell", { label: "建筑", value: structures.length + areas.filter((area) => area.type !== "area.warehouse.shell").length }],
    ["shell.outerWall", { label: "外墙", value: areas.filter((area) => area.type === "area.warehouse.shell").length }],
    ["vehicles", { label: "车位", value: parkingSpaces.length }],
    ["spotlights", { label: "射灯", value: fixtures.length }],
    ["device.ap", { label: "AP", value: devices.filter((device) => device.type === "network.ap").length }],
    ["coverage.ap", { label: "AP覆盖", value: devices.filter((device) => device.type === "network.ap" && cameraWithCoverage(device)).length }],
    ["device.fisheye", { label: "鱼眼", value: devices.filter((device) => device.type === "security.camera.fisheye").length }],
    ["coverage.fisheye", { label: "鱼眼覆盖", value: devices.filter((device) => device.type === "security.camera.fisheye" && cameraWithCoverage(device)).length }],
    ["device.dome", { label: "半球", value: devices.filter((device) => device.type === "security.camera.dome").length }],
    ["coverage.dome", { label: "半球覆盖", value: devices.filter((device) => device.type === "security.camera.dome" && cameraWithCoverage(device)).length }],
    ["device.bullet", [
      { label: "墙面枪机", value: devices.filter(wallBulletCamera).length },
      { label: "车尾监控", value: devices.filter(rearCamera).length },
    ]],
    ["coverage.bullet", [
      { label: "墙面覆盖", value: devices.filter((device) => wallBulletCamera(device) && cameraWithCoverage(device)).length },
      { label: "车尾覆盖", value: devices.filter((device) => rearCamera(device) && cameraWithCoverage(device)).length },
    ]],
    ["device.cabinet", { label: "机柜", value: devices.filter((device) => device.type === "network.cabinet" || device.type === "network.switch").length }],
    ["cables", { label: "线路", value: cables.filter((cable) => !["cabinet_cable", "spotlight_cable"].includes(cable.attributes?.layer_role || "")).length }],
    ["cables.cabinet", { label: "机柜电缆", value: cables.filter((cable) => (cable.attributes?.layer_role || "") === "cabinet_cable" || cable.type === "cable.cabinet_power").length }],
    ["cables.spotlight", { label: "射灯电缆", value: cables.filter((cable) => (cable.attributes?.layer_role || "") === "spotlight_cable" || cable.type === "cable.spotlight_power").length }],
  ]);
  return inputs
    .map((input) => input.dataset.layer)
    .filter((layer) => checkedLayers.has(layer) && layerStats.has(layer))
    .flatMap((layer) => layerStats.get(layer));
}

function renderStatSlots(elements, stats, mode) {
  elements.forEach((element, index) => {
    const stat = stats[index];
    const slot = element?.parentElement;
    if (!stat) {
      if (slot) slot.hidden = true;
      return;
    }
    if (slot) slot.hidden = false;
    if (mode === "metric") setMetricSlot(element, stat.value, stat.label);
    else setStatusSlot(element, stat.value, stat.label);
  });
}

function setStatusSlot(element, value, label) {
  if (!element) return;
  if (element.parentElement) element.parentElement.hidden = false;
  element.textContent = value;
  const textNode = [...(element.parentElement?.childNodes || [])].find((node) => node.nodeType === Node.TEXT_NODE);
  if (textNode) textNode.textContent = `${label} `;
}

function setMetricSlot(element, value, label) {
  if (!element) return;
  if (element.parentElement) element.parentElement.hidden = false;
  element.textContent = value;
  const labelElement = element.parentElement?.querySelector("span");
  if (labelElement) labelElement.textContent = label;
}

function renderReviewList(semantic) {
  if (!dom.reviewList) return;
  const auditItems = semantic.quality?.visual_audit?.items || [];
  const fallbackItems = (semantic.devices || [])
    .filter((device) => device.review_needed || Number(device.confidence || 1) < 0.75)
    .map((device) => ({
      label: device.label || device.id,
      category: device.type || "device",
      status: "review_needed",
      reason: device.attributes?.review_reason || "设备置信度较低或需要人工复核",
    }));
  const items = auditItems.length ? auditItems : fallbackItems;
  if (!items.length) {
    dom.reviewList.innerHTML = `<div class="inspector-empty">暂无待审核条目。</div>`;
    return;
  }
  dom.reviewList.innerHTML = items
    .slice(0, 40)
    .map((item) => {
      const title = item.label || item.object_id || item.source_key || "待审核";
      const meta = [item.category, item.status].filter(Boolean).join(" · ");
      const assetUrl = item.screenshot_asset?.url;
      const assetLink = assetUrl ? `<a href="${escapeHtml(assetUrl)}" target="_blank" rel="noreferrer">查看截图</a>` : "";
      return `<div class="review-item"><strong>${escapeHtml(title)}</strong><span>${escapeHtml(meta)}</span><small>${escapeHtml(item.reason || "")}</small>${assetLink}</div>`;
    })
    .join("");
}

function renderProjectNotes(semantic) {
  renderNoteList(dom.processNotesList, semantic?.process_notes || [], "暂无施工工艺要求原文。");
  renderNoteList(dom.removalNotesList, semantic?.removal_notes || [], "暂无老场地拆除清单原文。");
}

function renderNoteList(container, notes, emptyText) {
  if (!container) return;
  const cleanNotes = (Array.isArray(notes) ? notes : [])
    .map((note) => String(note || "").trim())
    .filter(Boolean);
  if (!cleanNotes.length) {
    container.innerHTML = `<div class="inspector-empty">${escapeHtml(emptyText)}</div>`;
    return;
  }
  container.innerHTML = cleanNotes
    .map((note, index) => `<div class="note-item"><span>${index + 1}</span><p>${escapeHtml(note)}</p></div>`)
    .join("");
}

function renderFrameDetection(semantic) {
  if (!dom.frameDetectionBar) return;
  if (!semantic) {
    dom.frameDetectionBar.classList.add("hidden");
    dom.framePanelRestore?.classList.add("hidden");
    if (dom.frameSwitchList) dom.frameSwitchList.innerHTML = "";
    return;
  }
  const frames = semanticFrames(semantic);
  const baseView = semantic.base_view || semantic.quality?.frame_detection?.base_view || null;
  const canonicalViews = Array.isArray(semantic.canonical_views)
    ? semantic.canonical_views
    : Array.isArray(semantic.quality?.frame_detection?.canonical_views)
    ? semantic.quality.frame_detection.canonical_views
    : [];
  const frameKinds = countBy(frames.map((frame) => frame.kind || "unknown"));
  const kindSummary = Object.entries(frameKinds)
    .map(([kind, count]) => `${kind}:${count}`)
    .join(" / ");
  dom.frameSummary.textContent = `frames ${frames.length}${kindSummary ? ` (${kindSummary})` : ""}`;
  dom.baseViewSummary.textContent = `base_view ${formatViewSummary(baseView)}`;
  dom.canonicalViewsSummary.textContent = `canonical_views ${canonicalViews.length}`;
  renderFrameSwitches(frames);
  renderFramePreview(frames);
  setFramePanelCollapsed(state.framePanelCollapsed, { skipRender: true });
  setFramePreviewCollapsed(state.framePreviewCollapsed);
  setFramePanelHidden(state.framePanelHidden);
  if (!state.framePanelHidden) dom.frameDetectionBar.classList.remove("hidden");
}

function renderFrameSwitches(frames) {
  if (!dom.frameSwitchList) return;
  const validFrames = frames.filter((frame) => frame?.bounds);
  dom.frameSwitchList.innerHTML = "";
  if (!validFrames.length) {
    dom.frameSwitchList.classList.add("hidden");
    return;
  }
  dom.frameSwitchList.classList.remove("hidden");
  validFrames.forEach((frame) => {
    const key = frameViewKey(frame);
    if (!key) return;
    if (!(key in state.frameViewFilters)) state.frameViewFilters[key] = true;
    const label = document.createElement("label");
    label.className = `frame-switch ${framePreviewClass(frame)}${state.frameViewFilters[key] ? "" : " off"}`;
    label.dataset.frameView = key;

    const input = document.createElement("input");
    input.type = "checkbox";
    input.checked = Boolean(state.frameViewFilters[key]);
    input.dataset.frameViewInput = key;
    input.addEventListener("change", () => {
      state.frameViewFilters[key] = input.checked;
      label.classList.toggle("off", !input.checked);
      if (state.project?.id) state.frameViewFiltersByProject[state.project.id] = { ...state.frameViewFilters };
      loadSemanticForFrameViews({ preserveView: true });
      renderFrameSwitches(frames);
    });

    const text = document.createElement("span");
    const name = document.createElement("b");
    name.textContent = framePreviewTitle(frame);
    const meta = document.createElement("small");
    meta.textContent = frameSwitchMeta(frame);
    text.append(name, meta);
    label.append(input, text);
    dom.frameSwitchList.appendChild(label);
  });
}

function frameSwitchMeta(frame) {
  if (frame.kind === "main_plan") return "仓库主体";
  if (frame.reference_only || frame.kind === "reference_plan") return "参考图";
  return "系统示意图";
}

function initFramePreviewPicker() {
  const svg = dom.framePreviewSvg;
  if (!svg) return;
  svg.addEventListener("click", (event) => {
    const target = event.target?.closest?.("[data-frame-index]");
    if (!target) return;
    const frame = state.framePreviewMap?.frames?.[Number(target.dataset.frameIndex)];
    if (!frame?.bounds) return;
    if (frame.kind !== "main_plan" || frame.reference_only) {
      logger.add("WARNING", `${framePreviewTitle(frame)} 是系统/参考图，不能作为仓库主平面；请使用绿色主图或拖拽框选现方案主平面。`);
      return;
    }
    if (frame?.bounds) {
      setManualBbox(frame.bounds, `已选择图框: ${frame.title || frame.kind || frame.frame_id}`);
    }
  });
  svg.addEventListener("pointerdown", (event) => {
    if (!state.framePreviewMap || event.target?.closest?.("[data-frame-index]")) return;
    const point = framePreviewCadPoint(event);
    if (!point) return;
    svg.setPointerCapture?.(event.pointerId);
    state.framePreviewDrag = { start: point, end: point, pointerId: event.pointerId };
    drawFramePreviewDrag();
  });
  svg.addEventListener("pointermove", (event) => {
    if (!state.framePreviewDrag || state.framePreviewDrag.pointerId !== event.pointerId) return;
    const point = framePreviewCadPoint(event);
    if (!point) return;
    state.framePreviewDrag.end = point;
    drawFramePreviewDrag();
  });
  svg.addEventListener("pointerup", finishFramePreviewDrag);
  svg.addEventListener("pointercancel", finishFramePreviewDrag);
}

function renderFramePreview(frames) {
  if (!dom.framePreview || !dom.framePreviewSvg) return;
  state.framePreviewDrag = null;
  state.framePreviewMap = null;
  dom.framePreviewSvg.innerHTML = "";
  const validFrames = frames.filter((frame) => frame?.bounds);
  if (!validFrames.length) {
    dom.framePreview.classList.add("hidden");
    return;
  }
  const bounds = frameCollectionBounds(validFrames);
  const width = 420;
  const height = 122;
  const pad = 12;
  const spanX = Math.max(bounds.max_x - bounds.min_x, 1);
  const spanY = Math.max(bounds.max_y - bounds.min_y, 1);
  const scale = Math.min((width - pad * 2) / spanX, (height - pad * 2) / spanY);
  state.framePreviewMap = { frames: validFrames, bounds, width, height, pad, scale };
  dom.framePreviewSvg.setAttribute("viewBox", `0 0 ${width} ${height}`);

  validFrames.forEach((frame, index) => {
    const rect = frameToPreviewRect(frame.bounds);
    const item = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    item.setAttribute("x", rect.x);
    item.setAttribute("y", rect.y);
    item.setAttribute("width", rect.width);
    item.setAttribute("height", rect.height);
    item.setAttribute("rx", "2");
    item.dataset.frameIndex = String(index);
    item.classList.add("frame-preview-rect", framePreviewClass(frame));
    item.setAttribute("aria-label", framePreviewTitle(frame));
    dom.framePreviewSvg.appendChild(item);

    const title = document.createElementNS("http://www.w3.org/2000/svg", "title");
    title.textContent = framePreviewTitle(frame);
    item.appendChild(title);

    const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
    label.setAttribute("x", rect.x + 4);
    label.setAttribute("y", Math.max(12, rect.y + 12));
    label.classList.add("frame-preview-label");
    label.textContent = framePreviewLabel(frame);
    dom.framePreviewSvg.appendChild(label);
  });
  dom.framePreview.classList.remove("hidden");
}

function frameCollectionBounds(frames) {
  return frames.reduce(
    (acc, frame) => {
      const bounds = frame.bounds;
      acc.min_x = Math.min(acc.min_x, Number(bounds.min_x));
      acc.min_y = Math.min(acc.min_y, Number(bounds.min_y));
      acc.max_x = Math.max(acc.max_x, Number(bounds.max_x));
      acc.max_y = Math.max(acc.max_y, Number(bounds.max_y));
      return acc;
    },
    { min_x: Infinity, min_y: Infinity, max_x: -Infinity, max_y: -Infinity },
  );
}

function frameToPreviewRect(bounds) {
  const map = state.framePreviewMap;
  const x1 = map.pad + (Number(bounds.min_x) - map.bounds.min_x) * map.scale;
  const x2 = map.pad + (Number(bounds.max_x) - map.bounds.min_x) * map.scale;
  const y1 = map.height - map.pad - (Number(bounds.max_y) - map.bounds.min_y) * map.scale;
  const y2 = map.height - map.pad - (Number(bounds.min_y) - map.bounds.min_y) * map.scale;
  return {
    x: Math.min(x1, x2),
    y: Math.min(y1, y2),
    width: Math.max(Math.abs(x2 - x1), 1),
    height: Math.max(Math.abs(y2 - y1), 1),
  };
}

function framePreviewClass(frame) {
  if (frame.kind === "main_plan") return "main-plan";
  if (frame.reference_only || frame.kind === "reference_plan") return "reference-plan";
  return "system-view";
}

function framePreviewLabel(frame) {
  if (frame.kind === "main_plan") return "主图";
  if (frame.reference_only || frame.kind === "reference_plan") return "参考图";
  return framePreviewSystemLabel(frame);
}

function framePreviewTitle(frame) {
  if (!frame) return "图框";
  if (frame.kind === "main_plan") return frame.title || "现方案主平面";
  if (frame.reference_only || frame.kind === "reference_plan") return frame.title || "参考图";
  return frame.title || framePreviewSystemLabel(frame);
}

function framePreviewSystemLabel(frame) {
  const labels = {
    monitor: "监控",
    network: "网络",
    cable: "电缆",
    cascade: "级联",
    network_broadcast: "网络&广播",
    cabinet_link: "机柜链路",
    cabinet_spotlight_power: "机柜&射灯",
  };
  const kind = frame?.system_view_kind || "";
  return labels[kind] || "系统图";
}

function framePreviewCadPoint(event) {
  const map = state.framePreviewMap;
  if (!map || !dom.framePreviewSvg) return null;
  const rect = dom.framePreviewSvg.getBoundingClientRect();
  const svgX = ((event.clientX - rect.left) / Math.max(rect.width, 1)) * map.width;
  const svgY = ((event.clientY - rect.top) / Math.max(rect.height, 1)) * map.height;
  return {
    x: (svgX - map.pad) / map.scale + map.bounds.min_x,
    y: (map.height - map.pad - svgY) / map.scale + map.bounds.min_y,
  };
}

function drawFramePreviewDrag() {
  if (!state.framePreviewDrag || !dom.framePreviewSvg) return;
  let dragRect = dom.framePreviewSvg.querySelector(".frame-preview-drag");
  if (!dragRect) {
    dragRect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    dragRect.classList.add("frame-preview-drag");
    dom.framePreviewSvg.appendChild(dragRect);
  }
  const bbox = normalizedBbox(state.framePreviewDrag.start, state.framePreviewDrag.end);
  const rect = frameToPreviewRect(bbox);
  dragRect.setAttribute("x", rect.x);
  dragRect.setAttribute("y", rect.y);
  dragRect.setAttribute("width", rect.width);
  dragRect.setAttribute("height", rect.height);
}

function finishFramePreviewDrag(event) {
  if (!state.framePreviewDrag || state.framePreviewDrag.pointerId !== event.pointerId) return;
  const bbox = normalizedBbox(state.framePreviewDrag.start, state.framePreviewDrag.end);
  const spanX = bbox.max_x - bbox.min_x;
  const spanY = bbox.max_y - bbox.min_y;
  state.framePreviewDrag = null;
  dom.framePreviewSvg?.querySelector(".frame-preview-drag")?.remove();
  if (spanX >= 1000 && spanY >= 1000) {
    setManualBbox(bbox, "已按拖拽框选主图 bbox");
  }
}

function normalizedBbox(start, end) {
  return {
    min_x: Math.min(start.x, end.x),
    min_y: Math.min(start.y, end.y),
    max_x: Math.max(start.x, end.x),
    max_y: Math.max(start.y, end.y),
  };
}

function setManualBbox(bounds, message) {
  if (!dom.bboxInput) return;
  dom.bboxInput.value = formatBbox(bounds);
  syncProjectActionButtons();
  logger.add("INFO", message);
}

function countBy(values) {
  return values.reduce((acc, value) => {
    acc[value] = (acc[value] || 0) + 1;
    return acc;
  }, {});
}

function formatViewSummary(view) {
  if (!view) return "-";
  const name = view.title || view.kind || view.view_id || view.frame_id || "-";
  const suffix = view.no_main_plan_mode ? " · 无主平面" : "";
  return `${name}${suffix}`;
}

function formatBbox(bbox) {
  if (!bbox) return "-";
  return [bbox.min_x, bbox.min_y, bbox.max_x, bbox.max_y]
    .map((value) => Number(value).toFixed(0))
    .join(",");
}

function renderInspector(entity, kind) {
  const attrs = entity.attributes || {};
  const coverage = entity.coverage || {};
  const position = entity.geometry?.position;
  const blockName = firstValue(entity.block_name, entity.original_block_name, attrs.camera_symbol_block_name, attrs.source_block_name, attrs.source_block_id);
  const coverageDistance = firstNumber(
    attrs.coverage_distance_m,
    attrs.infrared_distance_m,
    attrs.coverage_length_m,
    attrs.coverage_radius_m,
    coverage.length_m,
    coverage.radius_m,
  );
  const pixelLabel =
    firstValue(attrs.pixel_label, attrs.megapixel_label) ||
    (numberOrNull(attrs.pixel_wan) ? `${numberOrNull(attrs.pixel_wan)}万` : "") ||
    pixelLabelFromText(attrs.parameter_source_text || attrs.coverage_radius_source_block_name || "");
  const elevation = firstNumber(attrs.floor_elevation_m, attrs.install_height_m, attrs.height_m);
  const rows = [
    ["对象类型", entity.type || kind || "-"],
    ["编号", entity.label || entity.id || "-"],
    ["图层", entity.original_layer || "-"],
    ["块名", blockName || "-"],
    ["置信度", entity.confidence != null ? `${Math.round(entity.confidence * 100)}%` : "-"],
    ["实体句柄", entity.source_entity_id || "-"],
    ["标高", elevation != null ? `${elevation} m` : "-"],
  ];
  if (position) {
    rows.push(["坐标", `${Math.round(position.x)}, ${Math.round(position.y)} mm`]);
  }
  const lensMm = numberOrNull(attrs.lens_mm);
  if (lensMm != null) rows.push(["镜头 mm", `${lensMm} mm`]);
  if (coverageDistance != null) rows.push(["覆盖距离 m", `${coverageDistance} m`]);
  const infraredDistance = numberOrNull(attrs.infrared_distance_m);
  if (infraredDistance != null) rows.push(["红外距离 m", `${infraredDistance} m`]);
  if (pixelLabel) rows.push(["像素", pixelLabel]);
  if (attrs.camera_form || attrs.camera_model) rows.push(["摄像机形态", attrs.camera_form || attrs.camera_model]);
  if (attrs.coverage_source || attrs.coverage_visual_source) rows.push(["覆盖来源", attrs.coverage_source || attrs.coverage_visual_source]);
  if (attrs.coverage_radius_source || attrs.coverage_radius_source_kind) rows.push(["覆盖半径来源", attrs.coverage_radius_source || attrs.coverage_radius_source_kind]);
  if (attrs.coverage_angle_rule) rows.push(["覆盖角度规则", attrs.coverage_angle_rule]);
  if (attrs.raw_coverage_angle_deg != null) rows.push(["CAD原始角度", `${attrs.raw_coverage_angle_deg}°`]);
  if (coverage.radius_m != null) rows.push(["半径 m", `${coverage.radius_m} m`]);
  if (coverage.length_m != null) rows.push(["长度 m", `${coverage.length_m} m`]);
  if (coverage.angle_deg != null) rows.push(["角度 deg", `${coverage.angle_deg}°`]);
  if (attrs.floor_label) rows.push(["楼层", attrs.floor_label]);
  if (attrs.level) rows.push(["层号", `${attrs.level}F`]);
  if (attrs.rack_units) rows.push(["机柜规格", `${attrs.rack_units}U`]);
  if (attrs.role === "office_aggregation_42u") rows.push(["机柜角色", "办公室弱电汇聚"]);
  if (attrs.mount) rows.push(["安装方式", attrs.mount]);
  if (attrs.install_height_m) rows.push(["安装高度", `${attrs.install_height_m} m`]);
  if (attrs.floor_elevation_m) rows.push(["楼层标高", `${attrs.floor_elevation_m} m`]);
  if (attrs.room_height_m) rows.push(["层高", `${attrs.room_height_m} m`]);
  if (attrs.height_m) rows.push(["标高", `${attrs.height_m} m`]);
  if (attrs.deck_height_m) rows.push(["夹层高度", `${attrs.deck_height_m} m`]);
  if (attrs.vehicle_label) rows.push(["车辆类型", attrs.vehicle_label]);
  if (attrs.vehicle_length_m) rows.push(["车辆尺寸", `${attrs.vehicle_length_m}m × ${attrs.vehicle_width_m}m × ${attrs.vehicle_height_m}m`]);
  if (attrs.paired_camera_label) rows.push(["配套摄像头", attrs.paired_camera_label]);
  if (attrs.purpose) rows.push(["用途", attrs.purpose]);
  if (attrs.media) rows.push(["线缆介质", displayCableMedia(attrs.media)]);
  if (attrs.source_label && attrs.target_label) rows.push(["链路", `${attrs.source_label} -> ${attrs.target_label}`]);
  dom.inspector.className = "";
  dom.inspector.innerHTML = rows
    .map(([label, value]) => `<div class="inspector-row"><span>${escapeHtml(label)}</span><span>${escapeHtml(value)}</span></div>`)
    .join("");
  if (attrs.placement && entity.id) {
    const height = Number(attrs.install_height_m || elevation || 0);
    const editor = document.createElement("div");
    editor.className = "inspector-row";
    editor.innerHTML = `<span>手调高度 m</span><input id="placementHeightInput" type="number" min="0.2" max="16" step="0.1" value="${height}" />`;
    dom.inspector.appendChild(editor);
    const tip = document.createElement("div");
    tip.className = "inspector-row";
    tip.innerHTML = "<span>位置</span><span>在物体上按住拖动</span>";
    dom.inspector.appendChild(tip);
    editor.querySelector("input")?.addEventListener("change", (event) => {
      placement.updateSelectedHeight(entity.id, event.target.value);
    });
  }
}

function firstValue(...values) {
  return values.find((value) => value !== undefined && value !== null && String(value).trim() !== "");
}

function displayCableMedia(value) {
  const text = String(value || "");
  if (text === "六类线") return "六类网线";
  return text;
}

function firstNumber(...values) {
  for (const value of values) {
    const number = numberOrNull(value);
    if (number != null) return number;
  }
  return null;
}

function numberOrNull(value) {
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? number : null;
}

function pixelLabelFromText(text) {
  const match = String(text || "").match(/(\d{2,5})\s*(?:万|W)/i);
  return match ? `${match[1]}万` : "";
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

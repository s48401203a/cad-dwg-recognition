export class PlacementStudio {
  constructor({ api, scene, logger, getProject, applySemantic, onStatus }) {
    this.api = api;
    this.scene = scene;
    this.logger = logger;
    this.getProject = getProject;
    this.applySemantic = applySemantic;
    this.onStatus = onStatus || (() => {});
    this.catalog = null;
    this.overrides = { version: 1, site: {}, instances: [], circuits: [] };
    this.mode = "select";
    this.placeId = "network.ap.warehouse";
    this.pendingLights = [];
    this.pointer = null;
    this.selectedId = null;
    this.selectedIds = [];
    this.saveTimer = null;
    this.ready = false;
    this.measureVisible = false;
    this.measureHideTimer = null;
    this.measureRaf = null;
    this.measureEntityId = null;
    this.editMode = null;
    this.undoStack = [];
    this.persistGen = 0;
  }

  catalogItem(id) {
    return (this.catalog?.items || []).find((item) => item.id === id) || null;
  }

  async attach() {
    const dock = document.getElementById("placementDock");
    dock?.querySelectorAll("[data-place-mode]").forEach((button) => {
      button.addEventListener("click", () => this.setMode(button.dataset.placeMode, button.dataset.placeId || ""));
    });
    document.getElementById("placementFixButton")?.addEventListener("click", () => this.applyFixedHeights());
    document.getElementById("placementSwitchProject")?.addEventListener("click", () => {
      document.getElementById("projectButton")?.click();
    });
    document.getElementById("placementAlignRow")?.addEventListener("click", () => this.alignSelection("row"));
    document.getElementById("placementAlignCol")?.addEventListener("click", () => this.alignSelection("col"));
    document.getElementById("placementUndoButton")?.addEventListener("click", () => this.undo());
    const canvas = this.scene.renderer.domElement;
    canvas.addEventListener("pointerdown", (event) => this.onPointerDown(event), true);
    window.addEventListener("pointerdown", (event) => this.onShiftRightDown(event), true);
    window.addEventListener("contextmenu", (event) => this.onShiftRightMenu(event), true);
    window.addEventListener("keydown", (event) => this.onKeyDown(event));
    canvas.addEventListener("dragover", (event) => {
      if (!this.ready) return;
      event.preventDefault();
    });
    canvas.addEventListener("drop", (event) => {
      if (!this.ready) return;
      event.preventDefault();
      const id = event.dataTransfer?.getData("text/place-id");
      if (id) this.setMode("place", id);
      const pos = this.scene.pickGround(event);
      if (pos && this.mode === "place") this.placeSingle(pos);
    });
    window.addEventListener("pointermove", (event) => this.onPointerMove(event));
    window.addEventListener("pointerup", (event) => this.onPointerUp(event));
    window.addEventListener("pointercancel", () => this.releasePointer());
    this.syncButtons();
  }

  renderModules() {
    const root = document.getElementById("placementModules");
    if (!root) return;
    const groups = this.catalog?.groups || [];
    const items = this.catalog?.items || [];
    root.innerHTML = groups.map((group) => {
      const cards = items.filter((item) => item.group === group.id);
      if (!cards.length) return "";
      return `<div class="placement-group">
        <h3 class="placement-group-label">${group.label}</h3>
        <div class="placement-group-grid">
          ${cards.map((item) => `<button type="button" draggable="true" data-place-mode="place" data-place-id="${item.id}">${item.label}</button>`).join("")}
        </div>
      </div>`;
    }).join("");
    root.querySelectorAll("[data-place-mode]").forEach((button) => {
      button.addEventListener("click", () => this.setMode(button.dataset.placeMode, button.dataset.placeId || ""));
      button.addEventListener("dragstart", (event) => {
        this.setMode("place", button.dataset.placeId || "");
        event.dataTransfer?.setData("text/place-id", button.dataset.placeId || "");
        event.dataTransfer.effectAllowed = "copy";
      });
    });
  }

  reset() {
    this.ready = false;
    this.layoutArmed = false;
    this.overrides = { version: 1, site: {}, instances: [], circuits: [] };
    this.pendingLights = [];
    this.pointer = null;
    this.selectedId = null;
    this.selectedIds = [];
    this.mode = "select";
    this.editMode = null;
    if (this.scene?.controls) this.scene.controls.enabled = true;
    this.scene?.markSelected(null);
    this.hideMeasureHud();
    this.hideMarquee();
    this.undoStack = [];
    this.persistGen = 0;
  }

  async ensureForProject(project) {
    if (!project?.id) return false;
    this.reset();
    if (!this.catalog) this.catalog = await this.api.getModelCatalog();
    const namedStudio = String(project.name || "").includes("摆放试验场");
    if (project.placement_studio || namedStudio) {
      await this.api.ensurePlacementScene(project.id);
      this.overrides = await this.api.getModelOverrides(project.id);
      this.ready = true;
      this.undoStack = [];
      this.pushHistory();
      this.renderModules();
      this.syncButtons();
      this.onStatus(this.mode);
      return true;
    }
    this.ready = false;
    this.syncButtons();
    return false;
  }

  setMode(mode, placeId = "") {
    this.mode = mode === "move" ? "select" : mode;
    if (placeId) this.placeId = placeId;
    if (this.mode !== "select" && this.mode !== "box") this.editMode = null;
    if (this.mode !== "circuit") this.pendingLights = [];
    if (this.scene?.controls) this.scene.controls.enabled = true;
    this.syncButtons();
    this.onStatus(this.mode);
    this.logger?.add("INFO", `摆放工具: ${this.modeLabel()}`);
  }

  modeLabel() {
    if (this.mode === "place") return `单击地面放置 ${this.catalogItem(this.placeId)?.label || this.placeId}`;
    if (this.mode === "box") return "框选：在空白处拖出方框多选，Ctrl+拖也可框选";
    if (this.mode === "combo") return "单击地面放置车尾组合";
    if (this.mode === "circuit") return `单击放射灯 ${this.pendingLights.length}/3`;
    if (this.editMode === "aim") return "拖转朝向：在场地上拖动，枪机跟着转";
    if (this.editMode === "coverage") return "拖调覆盖：从设备拖到目标半径";
    return "拖预览：左键旋转，右键平移，滚轮缩放。点中模型再拖才移动物体。";
  }

  syncButtons() {
    const dock = document.getElementById("placementDock");
    const inspector = document.getElementById("placementInspectorSection");
    document.body.classList.toggle("placement-studio", Boolean(this.ready));
    if (dock) dock.classList.toggle("hidden", !this.ready);
    if (inspector) inspector.classList.toggle("hidden", !this.ready);
    const currentName = document.getElementById("placementCurrentName");
    if (currentName) currentName.textContent = this.getProject?.()?.name || "试验场";
    if (this.ready && !this.layoutArmed) {
      this.collapseOtherSections();
      this.layoutArmed = true;
    }
    if (this.ready && this.catalog && !document.querySelector("#placementModules [data-place-id]")) {
      this.renderModules();
    }
    if (this.ready) this.renderInstanceList();
    document.querySelectorAll("#placementDock [data-place-mode]").forEach((button) => {
      const mode = button.dataset.placeMode === "move" ? "select" : button.dataset.placeMode;
      const active = mode === this.mode
        && (!button.dataset.placeId || button.dataset.placeId === this.placeId);
      button.setAttribute("aria-pressed", active ? "true" : "false");
    });
    const hint = document.getElementById("placementHint");
    if (hint) hint.textContent = this.ready ? this.modeLabel() : "打开试验场后可用";
  }

  collapseOtherSections() {
    document.querySelectorAll("#sidePanel [data-panel-section]").forEach((section) => {
      if (section.dataset.panelSection === "placement") return;
      section.classList.add("panel-collapsed");
      section.querySelector("[data-section-toggle]")?.setAttribute("aria-expanded", "false");
    });
  }

  renderInstanceList() {
    const root = document.getElementById("placementInstanceList");
    if (!root) return;
    const items = this.overrides.instances || [];
    if (!items.length) {
      root.innerHTML = `<div class="inspector-empty">还没有放置模型。从左侧点选或拖到场地。</div>`;
      return;
    }
    root.innerHTML = items.map((item) => {
      const active = this.selectedIds.includes(item.id) ? " active" : "";
      return `<button type="button" class="placement-instance-item${active}" data-instance-id="${item.id}">${this.escape(item.label || item.type || item.id)}</button>`;
    }).join("");
    root.querySelectorAll("[data-instance-id]").forEach((button) => {
      button.addEventListener("click", (event) => {
        const item = items.find((entry) => entry.id === button.dataset.instanceId);
        if (!item) return;
        if (event.shiftKey) {
          const origin = this.copyPosition(item);
          this.stampFrom(item, { x: origin.x + 1500, y: origin.y });
          return;
        }
        this.selectEntity(item, { lingerMs: 1200 });
      });
    });
  }

  nextLabel(prefix) {
    const count = (this.overrides.instances || []).filter((item) => String(item.label || "").startsWith(prefix)).length;
    return `${prefix}${String(count + 1).padStart(2, "0")}`;
  }

  newId(prefix) {
    return `${prefix}_${Math.random().toString(16).slice(2, 10)}`;
  }

  makeInstance(catalogId, position, extras = {}) {
    const item = this.catalogItem(catalogId);
    if (!item) throw new Error(`未知模型 ${catalogId}`);
    const height = Number(item.install_height_m);
    return {
      id: extras.id || this.newId(item.family || "obj"),
      catalog_id: item.id,
      type: item.type,
      kind: item.kind || "device",
      label: extras.label || this.nextLabel((item.label || "对象").replace(/\s+/g, "")),
      geometry: extras.geometry || { type: "point", position: { x: position.x, y: position.y } },
      orientation: { angle_deg: extras.angle_deg || 0 },
      coverage: this.defaultCoverage(item),
      attributes: {
        install_height_m: height,
        mount: item.mount,
        zone: item.zone,
        role: item.role,
        rack_units: item.rack_units,
        top_edge_height_m: item.top_edge_height_m,
        radius_m: item.radius_m,
        vehicle_length_m: item.vehicle_length_m,
        vehicle_width_m: item.vehicle_width_m,
        vehicle_height_m: item.vehicle_height_m,
        vehicle_label: item.label,
        height_m: item.kind === "cable" ? height : undefined,
        placement: true,
        combo_id: extras.combo_id || null,
        circuit_id: extras.circuit_id || null,
      },
    };
  }

  defaultCoverage(item) {
    const type = item?.type || "";
    if (type === "network.ap") return { radius_m: Number(item.coverage_radius_m || 14) };
    if (type.startsWith("security.camera") && type !== "security.camera.fisheye") {
      return { length_m: Number(item.coverage_length_m || 20), angle_deg: 60 };
    }
    return undefined;
  }

  isAimable(item) {
    return this.scene?._isDirectionalCamera(item);
  }

  isCoverable(item) {
    const type = item?.type || "";
    return type === "network.ap" || this.isAimable(item);
  }

  setEditMode(mode) {
    this.editMode = mode === this.editMode ? null : mode;
    this.syncButtons();
    document.querySelectorAll("[data-edit-mode]").forEach((button) => {
      button.setAttribute("aria-pressed", button.dataset.editMode === this.editMode ? "true" : "false");
    });
    this.logger?.add("INFO", this.editMode ? this.modeLabel() : "已退出拖调");
  }

  cadAimAngle(origin, target) {
    return Math.atan2(Number(target.x) - Number(origin.x), -(Number(target.y) - Number(origin.y))) * (180 / Math.PI);
  }

  applyAim(item, pos) {
    const origin = this.instancePosition(item);
    if (!origin || !pos) return;
    item.orientation = { angle_deg: this.cadAimAngle(origin, pos) };
    this.scene.syncPlacementVisual(item);
    const input = document.querySelector('[data-place-field="angle"]');
    if (input) input.value = String(Math.round(item.orientation.angle_deg));
  }

  applyCoverageRadius(item, pos) {
    const origin = this.instancePosition(item);
    if (!origin || !pos) return;
    const meters = Math.max(1, Math.hypot(Number(pos.x) - origin.x, Number(pos.y) - origin.y) / 1000);
    if (item.type === "network.ap") {
      item.coverage = { ...(item.coverage || {}), radius_m: Number(meters.toFixed(2)) };
    } else {
      item.coverage = { ...(item.coverage || {}), length_m: Number(meters.toFixed(2)) };
    }
    this.scene.syncPlacementVisual(item);
    const input = document.querySelector('[data-place-field="coverage"]');
    if (input) input.value = String(item.type === "network.ap" ? item.coverage.radius_m : item.coverage.length_m);
  }

  flipAim() {
    const items = this.selectedItems().filter((item) => this.isAimable(item));
    if (!items.length) {
      this.logger?.add("WARNING", "请先选中枪机/车尾摄像头");
      return;
    }
    items.forEach((item) => {
      const next = (Number(item.orientation?.angle_deg || 0) + 180) % 360;
      item.orientation = { angle_deg: next < 0 ? next + 360 : next };
      this.scene.syncPlacementVisual(item);
    });
    this.persist({ preserveView: true });
    this.logger?.add("SUCCESS", `已反转 ${items.length} 个摄像头照射方向`);
  }

  makeSegment(catalogId, position) {
    const item = this.catalogItem(catalogId);
    const length = Number(item?.segment_length_m || 8) * 1000;
    return this.makeInstance(catalogId, position, {
      geometry: {
        type: "polyline",
        closed: item?.kind === "office" || item?.type === "building.rack",
        points: [
          { x: position.x - length / 2, y: position.y },
          { x: position.x + length / 2, y: position.y },
          ...(item?.type === "building.rack" || item?.type === "office.partition" ? [
            { x: position.x + length / 2, y: position.y + 800 },
            { x: position.x - length / 2, y: position.y + 800 },
          ] : []),
        ],
      },
    });
  }

  makeColumn(position) {
    return this.makeInstance("building.column", position, {
      geometry: { type: "Circle", position: { x: position.x, y: position.y }, center: { x: position.x, y: position.y }, radius: 300 },
    });
  }

  makeRack(position) {
    const w = 2400;
    const d = 1100;
    return this.makeInstance("building.rack", position, {
      geometry: {
        type: "polygon",
        closed: true,
        points: [
          { x: position.x - w / 2, y: position.y - d / 2 },
          { x: position.x + w / 2, y: position.y - d / 2 },
          { x: position.x + w / 2, y: position.y + d / 2 },
          { x: position.x - w / 2, y: position.y + d / 2 },
        ],
      },
    });
  }

  makeParking(position) {
    const item = this.catalogItem("parking.truck_bay");
    const length = Number(item?.vehicle_length_m || 9.6) * 1000;
    const width = Number(item?.vehicle_width_m || 2.45) * 1000;
    return this.makeInstance("parking.truck_bay", position, {
      geometry: {
        type: "polygon",
        closed: true,
        points: [
          { x: position.x - width / 2, y: position.y - length / 2 },
          { x: position.x + width / 2, y: position.y - length / 2 },
          { x: position.x + width / 2, y: position.y + length / 2 },
          { x: position.x - width / 2, y: position.y + length / 2 },
        ],
      },
    });
  }

  pickHit(event) {
    const mesh = this.scene.pickEntity(event, { skipCoverage: true, skipShell: true });
    if (mesh?.entity?.id) return mesh;
    const ground = this.scene.pickGround(event);
    if (!ground) return null;
    let best = null;
    let bestDist = 2800;
    for (const item of this.overrides.instances || []) {
      const point = item.geometry?.position;
      if (!point) continue;
      const dist = Math.hypot(Number(point.x) - ground.x, Number(point.y) - ground.y);
      if (dist < bestDist) {
        bestDist = dist;
        best = item;
      }
    }
    if (!best) return null;
    return {
      entity: best,
      kind: best.kind || "device",
      object: this.scene.findObjectByEntityId(best.id),
    };
  }

  selectedItems() {
    return (this.overrides.instances || []).filter((item) => this.selectedIds.includes(item.id));
  }

  instancePosition(item) {
    return item?.geometry?.position || item?.geometry?.center || null;
  }

  copyPosition(item) {
    const pos = this.instancePosition(item);
    return pos ? { x: Number(pos.x) || 0, y: Number(pos.y) || 0 } : { x: 0, y: 0 };
  }

  liveInstance(entity) {
    if (!entity?.id) return entity;
    return (this.overrides.instances || []).find((item) => item.id === entity.id) || entity;
  }

  syncInspectorPose(item) {
    const pos = this.instancePosition(item);
    if (!pos) return;
    const xInput = document.querySelector('[data-place-field="x"]');
    const yInput = document.querySelector('[data-place-field="y"]');
    if (xInput) xInput.value = String(Math.round(Number(pos.x) || 0));
    if (yInput) yInput.value = String(Math.round(Number(pos.y) || 0));
  }

  selectEntity(entity, options = {}) {
    if (!entity?.id) return;
    entity = this.liveInstance(entity) || entity;
    const opts = typeof options === "string" ? { kind: options } : options;
    if (opts.additive) {
      if (this.selectedIds.includes(entity.id)) {
        this.selectedIds = this.selectedIds.filter((id) => id !== entity.id);
      } else {
        this.selectedIds = [...this.selectedIds, entity.id];
      }
    } else if (opts.keepGroup && this.selectedIds.includes(entity.id)) {
      // keep current multi-selection for group drag
    } else {
      this.selectedIds = [entity.id];
    }
    this.selectedId = this.selectedIds.includes(entity.id) ? entity.id : (this.selectedIds[this.selectedIds.length - 1] || null);
    this.scene.markSelected(this.selectedItems());
    this.renderInspector();
    const measureTarget = this.selectedIds.length === 1 ? this.selectedItems()[0] : entity;
    if (this.selectedIds.length === 1 || opts.forceMeasure) {
      this.showMeasureHud(measureTarget, { lingerMs: opts.lingerMs ?? 1200 });
    } else {
      this.hideMeasureHud();
    }
  }

  wallBounds() {
    const shell = (this.scene?.semantic?.areas || []).find((area) => area.type === "area.warehouse.shell");
    const points = shell?.geometry?.points || [];
    if (points.length < 2) return null;
    const xs = points.map((point) => Number(point.x));
    const ys = points.map((point) => Number(point.y));
    return {
      minX: Math.min(...xs),
      maxX: Math.max(...xs),
      minY: Math.min(...ys),
      maxY: Math.max(...ys),
    };
  }

  wallDistances(pos = {}) {
    const bounds = this.wallBounds();
    if (!bounds) return { left: NaN, right: NaN, front: NaN, back: NaN };
    return {
      left: (Number(pos.x) - bounds.minX) / 1000,
      right: (bounds.maxX - Number(pos.x)) / 1000,
      front: (Number(pos.y) - bounds.minY) / 1000,
      back: (bounds.maxY - Number(pos.y)) / 1000,
    };
  }

  showMeasureHud(entity, { lingerMs = 0 } = {}) {
    if (!this.ready || !entity) return;
    const live = this.liveInstance(entity);
    this.measureEntityId = live?.id || entity.id;
    this.measureVisible = true;
    if (this.measureHideTimer) {
      clearTimeout(this.measureHideTimer);
      this.measureHideTimer = null;
    }
    this.renderMeasureHud(live);
    this.armMeasureLoop();
    if (lingerMs > 0) this.hideMeasureHud({ delayMs: lingerMs });
  }

  hideMeasureHud({ delayMs = 0 } = {}) {
    if (this.measureHideTimer) {
      clearTimeout(this.measureHideTimer);
      this.measureHideTimer = null;
    }
    const hide = () => {
      this.measureVisible = false;
      this.measureEntityId = null;
      const hud = document.getElementById("placementMeasureHud");
      if (hud) {
        hud.classList.add("hidden");
        hud.setAttribute("aria-hidden", "true");
      }
      this.scene?.clearMeasureGuides();
      if (this.measureRaf) {
        cancelAnimationFrame(this.measureRaf);
        this.measureRaf = null;
      }
    };
    if (delayMs > 0 && this.measureVisible) {
      this.measureHideTimer = window.setTimeout(hide, delayMs);
      return;
    }
    hide();
  }

  renderMeasureHud(entity) {
    const hud = document.getElementById("placementMeasureHud");
    if (hud) {
      hud.classList.add("hidden");
      hud.setAttribute("aria-hidden", "true");
    }
    if (!entity) return;
    this.scene?.drawMeasureGuides(entity, this.wallBounds());
  }

  positionMeasureHud(entity) {
    if (entity) this.scene?.drawMeasureGuides(entity, this.wallBounds());
  }

  armMeasureLoop() {
    if (this.measureRaf) return;
    const tick = () => {
      if (!this.measureVisible || !this.measureEntityId) {
        this.measureRaf = null;
        return;
      }
      const entity = (this.overrides.instances || []).find((item) => item.id === this.measureEntityId);
      if (entity && (this.pointer?.moving || this.pointer?.aiming || this.pointer?.covering)) {
        this.renderMeasureHud(entity);
      }
      this.measureRaf = requestAnimationFrame(tick);
    };
    this.measureRaf = requestAnimationFrame(tick);
  }

  cloneOverrides() {
    return {
      site: JSON.parse(JSON.stringify(this.overrides.site || {})),
      instances: JSON.parse(JSON.stringify(this.overrides.instances || [])),
      circuits: JSON.parse(JSON.stringify(this.overrides.circuits || [])),
      selectedIds: [...(this.selectedIds || [])],
    };
  }

  pushHistory() {
    const next = this.cloneOverrides();
    const last = this.undoStack[this.undoStack.length - 1];
    if (last && JSON.stringify(last.instances) === JSON.stringify(next.instances)
      && JSON.stringify(last.circuits) === JSON.stringify(next.circuits)
      && JSON.stringify(last.site) === JSON.stringify(next.site)) {
      return;
    }
    this.undoStack.push(next);
    if (this.undoStack.length > 40) this.undoStack.shift();
  }

  async undo() {
    if (!this.ready) return;
    if (this.undoStack.length < 2) {
      this.logger.add("WARNING", "没有可撤销的操作");
      return;
    }
    this.undoStack.pop();
    const prev = this.undoStack[this.undoStack.length - 1];
    this.overrides = {
      version: 1,
      site: JSON.parse(JSON.stringify(prev.site || {})),
      instances: JSON.parse(JSON.stringify(prev.instances || [])),
      circuits: JSON.parse(JSON.stringify(prev.circuits || [])),
    };
    this.selectedIds = [...(prev.selectedIds || [])];
    this.selectedId = this.selectedIds[this.selectedIds.length - 1] || null;
    this.hideMeasureHud();
    this.persistGen += 1;
    await this.persist({ preserveView: true, skipUndo: true });
    this.logger.add("SUCCESS", "已撤销上一步");
  }

  onKeyDown(event) {
    if (!this.ready) return;
    const key = String(event.key || "").toLowerCase();
    const undoKey = (event.metaKey || event.ctrlKey) && key === "z" && !event.shiftKey;
    if (!undoKey) return;
    const tag = String(event.target?.tagName || "");
    if (tag === "INPUT" || tag === "TEXTAREA" || event.target?.isContentEditable) return;
    event.preventDefault();
    this.undo();
  }

  onShiftRightDown(event) {
    if (!this.ready || event.button !== 2 || !event.shiftKey) return;
    event.preventDefault();
    event.stopPropagation();
    if (this.scene?.controls) this.scene.controls.enabled = false;
  }

  onShiftRightMenu(event) {
    if (!this.ready || !event.shiftKey) return;
    event.preventDefault();
    event.stopPropagation();
    if (this.scene?.controls) this.scene.controls.enabled = true;
    this.undo();
  }

  releasePointer() {
    this.pointer = null;
    if (this.scene?.controls) this.scene.controls.enabled = true;
    this.hideMarquee();
  }

  onPointerDown(event) {
    if (!this.ready) return;
    if (event.button === 2) return;
    if (event.button !== 0) return;
    const placing = this.mode === "place" || this.mode === "combo" || this.mode === "circuit";
    if (placing) {
      this.pointer = {
        x: event.clientX,
        y: event.clientY,
        placing: true,
        placeKind: this.mode,
        hit: null,
        dragged: false,
      };
      return;
    }
    const meshHit = this.scene.pickEntity(event, { skipCoverage: true, skipShell: true });
    const picked = meshHit?.entity?.id ? meshHit : null;
    const wantBox = !picked && (this.mode === "box" || event.altKey || event.ctrlKey);
    if (wantBox) {
      event.stopPropagation();
      event.stopImmediatePropagation();
      this.scene.controls.enabled = false;
      this.pointer = {
        x: event.clientX,
        y: event.clientY,
        placing: false,
        hit: null,
        dragged: false,
        moving: false,
        boxing: false,
        additive: Boolean(event.shiftKey),
        origins: [],
      };
      return;
    }
    if (event.shiftKey && !this.editMode && (this.mode === "select" || this.mode === "box")) {
      const ground = this.scene.pickGround(event);
      if (picked?.entity) {
        event.stopPropagation();
        event.stopImmediatePropagation();
        this.scene.controls.enabled = false;
        this.selectEntity(picked.entity, { lingerMs: 0, forceMeasure: true });
        this.pointer = {
          x: event.clientX,
          y: event.clientY,
          placing: false,
          hit: { entity: this.liveInstance(picked.entity) },
          dragged: false,
          moving: false,
          boxing: false,
          shiftStamp: true,
          origins: [],
        };
        return;
      }
      if (ground) {
        const source = this.selectedItems()[0];
        if (source?.catalog_id) {
          event.stopPropagation();
          event.stopImmediatePropagation();
          this.stampFrom(source, ground);
          return;
        }
      }
    }
    const editTarget = this.editMode && (picked?.entity && this.selectedIds.includes(picked.entity.id)
      ? picked.entity
      : this.selectedItems()[0]);
    if (this.editMode && editTarget && (this.editMode === "aim" || this.editMode === "coverage")) {
      event.stopPropagation();
      event.stopImmediatePropagation();
      this.scene.controls.enabled = false;
      this.pointer = {
        x: event.clientX,
        y: event.clientY,
        placing: false,
        hit: { entity: editTarget },
        dragged: false,
        moving: false,
        boxing: false,
        aiming: this.editMode === "aim",
        covering: this.editMode === "coverage",
        origins: [],
      };
      this.selectEntity(editTarget, { keepGroup: true, lingerMs: 0, forceMeasure: true });
      return;
    }
    this.pointer = {
      x: event.clientX,
      y: event.clientY,
      placing: false,
      hit: picked,
      dragged: false,
      moving: false,
      boxing: false,
      aiming: false,
      covering: false,
      additive: Boolean(event.shiftKey),
      origins: [],
    };
    if (picked?.entity) {
      event.stopPropagation();
      event.stopImmediatePropagation();
      this.scene.controls.enabled = false;
      this.selectEntity(picked.entity, {
        additive: event.shiftKey,
        keepGroup: !event.shiftKey,
        lingerMs: 0,
        forceMeasure: true,
      });
      this.pointer.origins = this.selectedItems().map((item) => ({
        id: item.id,
        pos: this.copyPosition(item),
      }));
      this.pointer.anchor = this.copyPosition(picked.entity);
      return;
    }
    this.pointer.clickClear = true;
  }

  onPointerMove(event) {
    if (!this.pointer) return;
    const dx = event.clientX - this.pointer.x;
    const dy = event.clientY - this.pointer.y;
    if (!this.pointer.dragged && Math.hypot(dx, dy) < 6) return;
    this.pointer.dragged = true;
    if (this.pointer.placing || this.pointer.clickClear) return;
    if (!this.pointer.hit?.entity) {
      this.pointer.boxing = true;
      this.updateMarquee(this.pointer.x, this.pointer.y, event.clientX, event.clientY);
      return;
    }
    const pos = this.scene.pickGround(event);
    if (!pos) return;
    this.pointer.moving = true;
    if (this.pointer.aiming) {
      this.applyAim(this.pointer.hit.entity, pos);
      this.showMeasureHud(this.pointer.hit.entity, { lingerMs: 0, forceMeasure: true });
      return;
    }
    if (this.pointer.covering) {
      this.applyCoverageRadius(this.pointer.hit.entity, pos);
      this.showMeasureHud(this.pointer.hit.entity, { lingerMs: 0, forceMeasure: true });
      return;
    }
    const anchor = this.pointer.anchor || this.copyPosition(this.pointer.hit.entity);
    const delta = { x: pos.x - anchor.x, y: pos.y - anchor.y };
    const targets = this.pointer.origins?.length ? this.pointer.origins : [{ id: this.pointer.hit.entity.id, pos: anchor }];
    targets.forEach((origin) => {
      this.moveInstance(origin.id, { x: origin.pos.x + delta.x, y: origin.pos.y + delta.y });
      const item = (this.overrides.instances || []).find((entry) => entry.id === origin.id);
      if (item) this.scene.syncPlacementVisual(item);
    });
    this.scene.markSelected(this.selectedItems());
    const live = this.liveInstance(this.pointer.hit.entity);
    this.showMeasureHud(live, { lingerMs: 0, forceMeasure: true });
    this.syncInspectorPose(live);
  }

  onPointerUp(event) {
    if (!this.pointer) return;
    const snapshot = this.pointer;
    this.releasePointer();
    if (snapshot.placing && !snapshot.dragged) {
      const pos = this.scene.pickGround(event);
      if (!pos) {
        this.logger.add("WARNING", "没有点到地面，请点场地网格");
        return;
      }
      try {
        if (snapshot.placeKind === "place") this.placeSingle(pos);
        else if (snapshot.placeKind === "combo") this.placeCombo(pos);
        else this.placeCircuitLight(pos);
      } catch (error) {
        this.logger.add("ERROR", `放置失败: ${error.message}`);
      }
      return;
    }
    if (snapshot.shiftStamp && !snapshot.dragged && snapshot.hit?.entity) {
      const source = this.liveInstance(snapshot.hit.entity);
      const origin = this.copyPosition(source);
      this.stampFrom(source, { x: origin.x + 1500, y: origin.y });
      return;
    }
    if (snapshot.boxing) {
      const boxed = this.instancesInScreenRect(snapshot.x, snapshot.y, event.clientX, event.clientY);
      if (snapshot.additive) {
        const extra = boxed.map((item) => item.id).filter((id) => !this.selectedIds.includes(id));
        this.selectedIds = [...this.selectedIds, ...extra];
      } else {
        this.selectedIds = boxed.map((item) => item.id);
      }
      this.selectedId = this.selectedIds[this.selectedIds.length - 1] || null;
      this.scene.markSelected(this.selectedItems());
      this.renderInspector();
      if (this.selectedIds.length === 1) this.showMeasureHud(this.selectedItems()[0], { lingerMs: 1200 });
      else this.hideMeasureHud();
      return;
    }
    if (!snapshot.hit?.entity && !snapshot.dragged) {
      this.selectedIds = [];
      this.selectedId = null;
      this.scene.markSelected(null);
      this.renderInspector();
      this.hideMeasureHud();
      return;
    }
    if (snapshot.moving || snapshot.aiming || snapshot.covering) this.persist({ preserveView: true });
    this.hideMeasureHud({ delayMs: snapshot.moving || snapshot.aiming || snapshot.covering ? 80 : 1200 });
  }

  updateMarquee(x0, y0, x1, y1) {
    const box = document.getElementById("placementMarquee");
    const wrap = document.getElementById("canvasWrap");
    if (!box || !wrap) return;
    const rect = wrap.getBoundingClientRect();
    const left = Math.min(x0, x1) - rect.left;
    const top = Math.min(y0, y1) - rect.top;
    box.classList.remove("hidden");
    box.style.left = `${left}px`;
    box.style.top = `${top}px`;
    box.style.width = `${Math.abs(x1 - x0)}px`;
    box.style.height = `${Math.abs(y1 - y0)}px`;
  }

  hideMarquee() {
    document.getElementById("placementMarquee")?.classList.add("hidden");
  }

  instancesInScreenRect(x0, y0, x1, y1) {
    const mapper = this.scene?.mapper;
    const camera = this.scene?.camera;
    if (!mapper || !camera) return [];
    const minX = Math.min(x0, x1);
    const maxX = Math.max(x0, x1);
    const minY = Math.min(y0, y1);
    const maxY = Math.max(y0, y1);
    return (this.overrides.instances || []).filter((item) => {
      const pos = this.instancePosition(item);
      if (!pos) return false;
      const world = mapper.toVector3(pos, 0);
      const ndc = world.clone().project(camera);
      if (ndc.z < -1 || ndc.z > 1) return false;
      const rect = this.scene.renderer.domElement.getBoundingClientRect();
      const sx = rect.left + (ndc.x * 0.5 + 0.5) * rect.width;
      const sy = rect.top + (-ndc.y * 0.5 + 0.5) * rect.height;
      return sx >= minX && sx <= maxX && sy >= minY && sy <= maxY;
    });
  }

  moveInstance(entityId, pos) {
    const item = (this.overrides.instances || []).find((entry) => entry.id === entityId);
    if (!item) return;
    if (item.geometry?.position) {
      item.geometry.position = { x: pos.x, y: pos.y };
      return;
    }
    if (Array.isArray(item.geometry?.points) && item.geometry.points.length) {
      const first = item.geometry.points[0];
      const dx = pos.x - first.x;
      const dy = pos.y - first.y;
      item.geometry.points = item.geometry.points.map((point) => ({ x: point.x + dx, y: point.y + dy }));
    }
  }

  buildInstanceAt(catalogId, pos) {
    const item = this.catalogItem(catalogId);
    if (!item) throw new Error(`未知模型 ${catalogId}`);
    if (item.kind === "cable" || item.type === "office.partition" || item.type === "logistics.conveyor_belt") {
      return this.makeSegment(catalogId, pos);
    }
    if (item.type === "building.column") return this.makeColumn(pos);
    if (item.type === "building.rack") return this.makeRack(pos);
    if (item.kind === "parking") return this.makeParking(pos);
    return this.makeInstance(catalogId, pos);
  }

  stampFrom(source, pos) {
    const catalogId = source?.catalog_id;
    if (!catalogId || !this.catalogItem(catalogId)) {
      this.logger.add("WARNING", "先点一个已放的模型，再按住 Shift 点地面添加同款");
      return null;
    }
    const instance = this.buildInstanceAt(catalogId, pos);
    instance.orientation = { angle_deg: Number(source.orientation?.angle_deg || 0) };
    if (source.coverage) instance.coverage = { ...source.coverage };
    instance.attributes = {
      ...(instance.attributes || {}),
      install_height_m: source.attributes?.install_height_m ?? instance.attributes?.install_height_m,
    };
    this.overrides.instances.push(instance);
    this.selectedId = instance.id;
    this.selectedIds = [instance.id];
    this.placeId = catalogId;
    this.setMode("select");
    this.logger.add("SUCCESS", `已添加 ${instance.label}（Shift 再点地面可继续）`);
    this.persist({ preserveView: true });
    return instance;
  }

  placeSingle(pos) {
    const item = this.catalogItem(this.placeId);
    let instance;
    if (item?.kind === "cable" || item?.type === "office.partition" || item?.type === "logistics.conveyor_belt") {
      instance = this.makeSegment(this.placeId, pos);
    } else if (item?.type === "building.column") {
      instance = this.makeColumn(pos);
    } else if (item?.type === "building.rack") {
      instance = this.makeRack(pos);
    } else if (item?.kind === "parking") {
      instance = this.makeParking(pos);
    } else {
      instance = this.makeInstance(this.placeId, pos);
    }
    this.overrides.instances.push(instance);
    this.logger.add("SUCCESS", `已放置 ${instance.label}，可直接拖动调整`);
    this.setMode("select");
    this.selectedId = instance.id;
    this.selectedIds = [instance.id];
    this.persist({ preserveView: true });
  }

  placeCombo(pos) {
    const comboId = this.newId("combo");
    const camera = this.makeInstance("security.camera.rear", pos, { combo_id: comboId, label: this.nextLabel("CW-") });
    const light = this.makeInstance("lighting.floodlight", { x: pos.x + 400, y: pos.y }, { combo_id: comboId, label: this.nextLabel("SL-") });
    camera.attributes.combo_id = comboId;
    light.attributes.combo_id = comboId;
    this.overrides.instances.push(camera, light);
    this.logger.add("SUCCESS", `已放置车尾组合 ${camera.label} + ${light.label}`);
    this.setMode("select");
    this.selectedId = camera.id;
    this.selectedIds = [camera.id, light.id];
    this.persist({ preserveView: true });
  }

  placeCircuitLight(pos) {
    const light = this.makeInstance("lighting.floodlight", pos, { label: this.nextLabel("SL-") });
    this.overrides.instances.push(light);
    this.pendingLights.push(light.id);
    if (this.pendingLights.length < 3) {
      this.logger.add("INFO", `射灯 ${this.pendingLights.length}/3，再单击 ${3 - this.pendingLights.length} 盏生成空开`);
      this.syncButtons();
      this.persist({ preserveView: true });
      return;
    }
    const groupIds = this.pendingLights.slice(-3);
    const members = this.overrides.instances.filter((item) => groupIds.includes(item.id));
    const cx = members.reduce((sum, item) => sum + Number(item.geometry?.position?.x || 0), 0) / members.length;
    const cy = members.reduce((sum, item) => sum + Number(item.geometry?.position?.y || 0), 0) / members.length;
    const circuitId = this.newId("ckt");
    const breaker = this.makeInstance("power.breaker", { x: cx, y: cy + 4000 }, { label: this.nextLabel("空开") });
    breaker.attributes.circuit_id = circuitId;
    const cable = this.makeInstance("cable.spotlight_power", { x: cx, y: cy }, {
      label: this.nextLabel("射灯强电"),
      geometry: {
        type: "polyline",
        points: [{ x: breaker.geometry.position.x, y: breaker.geometry.position.y }, ...members.map((item) => ({ x: item.geometry.position.x, y: item.geometry.position.y }))],
      },
    });
    cable.attributes.circuit_id = circuitId;
    cable.attributes.height_m = 3.0;
    members.forEach((item) => {
      item.attributes.circuit_id = circuitId;
    });
    this.overrides.instances.push(breaker, cable);
    this.overrides.circuits.push({ id: circuitId, breaker_id: breaker.id, fixture_ids: groupIds, cable_id: cable.id });
    this.pendingLights = [];
    this.logger.add("SUCCESS", `已生成空开 ${breaker.label} 和一组强电`);
    this.setMode("select");
    this.selectedId = breaker.id;
    this.selectedIds = [breaker.id];
    this.persist({ preserveView: true });
  }

  async applyFixedHeights() {
    const project = this.getProject();
    if (!this.ready || !project?.id) return;
    this.overrides = await this.api.saveModelOverrides(project.id, {
      ...this.overrides,
      apply_standard_heights: true,
    });
    this.logger.add("SUCCESS", "已恢复标准初始高度，仍可继续手调");
    await this.reload();
  }

  syncCircuitRoutes() {
    const byId = Object.fromEntries((this.overrides.instances || []).map((item) => [item.id, item]));
    for (const circuit of this.overrides.circuits || []) {
      const cable = byId[circuit.cable_id];
      const breaker = byId[circuit.breaker_id];
      const lights = (circuit.fixture_ids || []).map((id) => byId[id]).filter(Boolean);
      if (!cable || !breaker || !lights.length) continue;
      cable.geometry = {
        type: "polyline",
        points: [
          { ...breaker.geometry.position },
          ...lights.map((item) => ({ ...item.geometry.position })),
        ],
      };
    }
  }

  async persist(options = {}) {
    const project = this.getProject();
    if (!this.ready || !project?.id) return;
    this.syncCircuitRoutes();
    if (!options.skipUndo) this.pushHistory();
    const gen = ++this.persistGen;
    try {
      const saved = await this.api.saveModelOverrides(project.id, {
        site: this.overrides.site || {},
        instances: this.overrides.instances || [],
        circuits: this.overrides.circuits || [],
      });
      if (gen !== this.persistGen) return;
      this.overrides = saved;
      await this.reload(options);
    } catch (error) {
      if (gen !== this.persistGen) return;
      this.logger.add("ERROR", `保存摆放失败: ${error.message}`);
    }
  }

  async reload(options = {}) {
    const project = this.getProject();
    if (!project?.id) return;
    const exported = await this.api.exportProject(project.id, { drawing_id: project.current_drawing_id });
    const semantic = exported.schema_version ? exported : exported.drawings?.[0];
    if (semantic) this.applySemantic(semantic, { preserveView: options.preserveView !== false });
    const selected = this.selectedItems();
    if (selected.length) {
      this.scene.markSelected(selected);
      this.renderInspector();
    } else {
      this.renderInspector();
    }
  }

  renderInspector() {
    const root = document.getElementById("placementInspector");
    if (!root) return;
    this.renderInstanceList();
    const items = this.selectedItems();
    if (!items.length) {
      root.className = "inspector-empty";
      root.textContent = "点选或框选模型后，可改参数、批量移动，或横排/竖排对齐。";
      return;
    }
    if (items.length > 1) {
      const height = Number(items[0].attributes?.install_height_m || 0);
      const angle = Number(items[0].orientation?.angle_deg || 0);
      root.className = "";
      root.innerHTML = `<div class="placement-multi-summary">已选 ${items.length} 个模型</div>
        <div class="placement-param-grid">
          <label>统一高度 m<input data-place-field="height" type="number" min="0" max="16" step="0.1" value="${height}" /></label>
          <label>统一朝向 °<input data-place-field="angle" type="number" step="5" value="${angle}" /></label>
        </div>
        <div class="placement-param-actions">
          <button type="button" data-align="row">横排对齐</button>
          <button type="button" data-align="col">竖排对齐</button>
        </div>
        <div class="placement-param-actions">
          <button type="button" id="placementApplyParams">应用</button>
          <button type="button" id="placementDelete">删除</button>
        </div>`;
      root.querySelector("[data-align=row]")?.addEventListener("click", () => this.alignSelection("row"));
      root.querySelector("[data-align=col]")?.addEventListener("click", () => this.alignSelection("col"));
      root.querySelector("#placementApplyParams")?.addEventListener("click", () => this.applyInspector(null, root));
      root.querySelector("#placementDelete")?.addEventListener("click", () => this.deleteSelected());
      return;
    }
    const item = items[0];
    const attrs = item.attributes || {};
    const pos = item.geometry?.position || item.geometry?.center || {};
    const angle = Number(item.orientation?.angle_deg || 0);
    const aimable = this.isAimable(item);
    const coverable = this.isCoverable(item);
    const coverageValue = item.type === "network.ap"
      ? Number(item.coverage?.radius_m || 14)
      : Number(item.coverage?.length_m || 20);
    const coverageLabel = item.type === "network.ap" ? "覆盖半径 m" : "照射距离 m";
    root.className = "";
    root.innerHTML = `<div class="placement-param-grid">
      <label>名称<input data-place-field="label" type="text" value="${this.escape(item.label || "")}" /></label>
      <label>类型<input type="text" value="${this.escape(item.type || "")}" disabled /></label>
      <label>X mm<input data-place-field="x" type="number" step="100" value="${Math.round(Number(pos.x || 0))}" /></label>
      <label>Y mm<input data-place-field="y" type="number" step="100" value="${Math.round(Number(pos.y || 0))}" /></label>
      <label>高度 m<input data-place-field="height" type="number" min="0" max="16" step="0.1" value="${Number(attrs.install_height_m || 0)}" /></label>
      <label>朝向 °<input data-place-field="angle" type="number" step="5" value="${Math.round(angle)}" /></label>
      ${coverable ? `<label>${coverageLabel}<input data-place-field="coverage" type="number" min="1" max="80" step="0.5" value="${coverageValue}" /></label>` : ""}
    </div>
    <div class="placement-param-actions">
      ${aimable ? `<button type="button" data-edit-mode="aim" aria-pressed="${this.editMode === "aim" ? "true" : "false"}">拖转朝向</button>
      <button type="button" id="placementFlipAim">反转照射</button>` : ""}
      ${coverable ? `<button type="button" data-edit-mode="coverage" aria-pressed="${this.editMode === "coverage" ? "true" : "false"}">拖调覆盖</button>` : ""}
      <button type="button" id="placementApplyParams">应用</button>
      <button type="button" id="placementDelete">删除</button>
    </div>`;
    root.querySelector('[data-place-field="angle"]')?.addEventListener("focus", () => {
      if (aimable) this.setEditMode("aim");
    });
    root.querySelector('[data-place-field="coverage"]')?.addEventListener("focus", () => {
      if (coverable) this.setEditMode("coverage");
    });
    root.querySelectorAll("[data-edit-mode]").forEach((button) => {
      button.addEventListener("click", () => this.setEditMode(button.dataset.editMode));
    });
    root.querySelector("#placementFlipAim")?.addEventListener("click", () => this.flipAim());
    root.querySelector("#placementApplyParams")?.addEventListener("click", () => this.applyInspector(item.id, root));
    root.querySelector("#placementDelete")?.addEventListener("click", () => this.deleteSelected());
  }

  escape(value) {
    return String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll('"', "&quot;");
  }

  applyInspector(entityId, root) {
    const read = (name) => root.querySelector(`[data-place-field="${name}"]`)?.value;
    const targets = entityId
      ? (this.overrides.instances || []).filter((entry) => entry.id === entityId)
      : this.selectedItems();
    if (!targets.length) return;
    targets.forEach((item) => {
      if (read("label") && targets.length === 1) item.label = read("label") || item.label;
      const x = Number(read("x"));
      const y = Number(read("y"));
      if (targets.length === 1 && Number.isFinite(x) && Number.isFinite(y)) {
        if (item.geometry?.position) item.geometry.position = { x, y };
        if (item.geometry?.center) item.geometry.center = { x, y };
      }
      if (read("height") !== undefined && read("height") !== "") {
        item.attributes = {
          ...(item.attributes || {}),
          install_height_m: Number(read("height")),
        };
      }
      if (read("angle") !== undefined && read("angle") !== "") {
        item.orientation = { angle_deg: Number(read("angle")) };
      }
      if (read("coverage") !== undefined && read("coverage") !== "") {
        const value = Number(read("coverage"));
        if (item.type === "network.ap") item.coverage = { ...(item.coverage || {}), radius_m: value };
        else if (this.isAimable(item)) item.coverage = { ...(item.coverage || {}), length_m: value, angle_deg: item.coverage?.angle_deg || 60 };
      }
    });
    this.persist({ preserveView: true });
  }

  deleteSelected() {
    const ids = new Set(this.selectedIds);
    if (!ids.size && this.selectedId) ids.add(this.selectedId);
    this.overrides.instances = (this.overrides.instances || []).filter((item) => !ids.has(item.id));
    this.overrides.circuits = (this.overrides.circuits || []).filter((circuit) => !ids.has(circuit.breaker_id) && !ids.has(circuit.cable_id) && !(circuit.fixture_ids || []).some((id) => ids.has(id)));
    this.selectedIds = [];
    this.selectedId = null;
    this.persist({ preserveView: true });
  }

  deleteInstance(entityId) {
    this.selectedIds = [entityId];
    this.deleteSelected();
  }

  alignSelection(axis) {
    const items = this.selectedItems().filter((item) => this.instancePosition(item));
    if (items.length < 2) {
      this.logger?.add("WARNING", "请先框选至少 2 个模型再对齐");
      return;
    }
    const xs = items.map((item) => this.instancePosition(item).x);
    const ys = items.map((item) => this.instancePosition(item).y);
    const minGap = 1500;
    if (axis === "row") {
      const y = ys.reduce((sum, value) => sum + value, 0) / ys.length;
      const sorted = [...items].sort((a, b) => this.instancePosition(a).x - this.instancePosition(b).x);
      const minX = Math.min(...xs);
      const maxX = Math.max(...xs);
      const span = maxX - minX;
      const even = span >= minGap * (sorted.length - 1);
      sorted.forEach((item, index) => {
        const x = even
          ? minX + (span / (sorted.length - 1)) * index
          : (minX + maxX) / 2 + (index - (sorted.length - 1) / 2) * minGap;
        item.geometry.position = { x, y };
      });
      this.logger?.add("SUCCESS", `已横排对齐 ${sorted.length} 个模型`);
    } else {
      const x = xs.reduce((sum, value) => sum + value, 0) / xs.length;
      const sorted = [...items].sort((a, b) => this.instancePosition(a).y - this.instancePosition(b).y);
      const minY = Math.min(...ys);
      const maxY = Math.max(...ys);
      const span = maxY - minY;
      const even = span >= minGap * (sorted.length - 1);
      sorted.forEach((item, index) => {
        const y = even
          ? minY + (span / (sorted.length - 1)) * index
          : (minY + maxY) / 2 + (index - (sorted.length - 1) / 2) * minGap;
        item.geometry.position = { x, y };
      });
      this.logger?.add("SUCCESS", `已竖排对齐 ${sorted.length} 个模型`);
    }
    this.persist({ preserveView: true });
  }

  updateSelectedHeight(entityId, heightM) {
    const item = (this.overrides.instances || []).find((entry) => entry.id === entityId);
    if (!item) return;
    item.attributes = { ...(item.attributes || {}), install_height_m: Number(heightM) };
    this.selectedId = entityId;
    this.persist({ preserveView: true });
  }
}

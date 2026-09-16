import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { CSS2DObject, CSS2DRenderer } from "three/addons/renderers/CSS2DRenderer.js";
import { CoordMapper } from "./CoordMapper.js";
import { DeviceFactory } from "./DeviceFactory.js?v=64";
import { AreaRenderer } from "./AreaRenderer.js?v=60";
import { CableRenderer } from "./CableRenderer.js";
import { LabelRenderer } from "./LabelRenderer.js";
import { VehicleRenderer } from "./VehicleRenderer.js?v=62";
import { OfficeRenderer } from "./OfficeRenderer.js?v=76";

const COVERAGE_GROUPS = new Set(["coverage.ap", "coverage.fisheye", "coverage.dome", "coverage.bullet"]);
const DETAIL_MODEL_GROUPS = new Set(["device.ap", "device.fisheye", "device.dome", "device.bullet", "device.cabinet", "vehicles", "spotlights"]);
const CABLE_GROUPS = new Set(["cables", "cables.cabinet", "cables.spotlight"]);
const DETAIL_UPDATE_INTERVAL_MS = 140;
const DETAIL_MODES = new Set(["full", "adaptive"]);
const DEFERRED_DEVICE_LAYERS = new Set([
  "labels",
  "coverage.ap",
  "coverage.fisheye",
  "coverage.dome",
  "coverage.bullet",
  "cables",
  "cables.cabinet",
  "cables.spotlight",
  "spotlights",
]);
const DEFAULT_MODEL_SCALE_PERCENT = 100;
const MIN_MODEL_SCALE_PERCENT = 100;
const MAX_MODEL_SCALE_PERCENT = 300;
const AP_LAYOUT_SPACING_FACTOR = 0.55;
const AP_LAYOUT_RADIUS_LIMITS = {
  office: { min: 4, max: 8, fallback: 6 },
  warehouse: { min: 8, max: 16, fallback: 14 },
};
const TOWER_FLOOR_LAYERS = new Set(["tower.level1", "tower.level2"]);

export class SceneBuilder {
  constructor(canvas, container) {
    this.canvas = canvas;
    this.container = container;
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x070807);
    this.camera = new THREE.PerspectiveCamera(45, 1, 0.1, 5000);
    this.renderer = new THREE.WebGLRenderer({
      canvas,
      antialias: false,
      powerPreference: "high-performance",
    });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.25));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.4;
    this.labelRenderer = new CSS2DRenderer();
    this.labelRenderer.domElement.style.position = "absolute";
    this.labelRenderer.domElement.style.inset = "0";
    this.labelRenderer.domElement.style.pointerEvents = "none";
    this.container.appendChild(this.labelRenderer.domElement);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.05;
    this.controls.enablePan = true;
    this.controls.enableRotate = true;
    this.controls.enableZoom = true;
    this.controls.screenSpacePanning = true;
    this.controls.mouseButtons.LEFT = THREE.MOUSE.ROTATE;
    this.controls.mouseButtons.MIDDLE = THREE.MOUSE.DOLLY;
    this.controls.mouseButtons.RIGHT = THREE.MOUSE.PAN;
    this.selectionRoot = new THREE.Group();
    this.selectionRoot.name = "selection";
    this.scene.add(this.selectionRoot);
    this.measureRoot = new THREE.Group();
    this.measureRoot.name = "measure";
    this.scene.add(this.measureRoot);
    this.selectedEntityIds = [];
    this.raycaster = new THREE.Raycaster();
    this.pointer = new THREE.Vector2();
    this.animationClock = new THREE.Clock();
    this.groups = {};
    this.layerVisibility = {};
    this.deviceFactory = new DeviceFactory();
    this.areaRenderer = new AreaRenderer();
    this.cableRenderer = new CableRenderer();
    this.labelRendererFactory = new LabelRenderer();
    this.vehicleRenderer = new VehicleRenderer();
    this.officeRenderer = new OfficeRenderer();
    this.onSelect = null;
    this.semantic = null;
    this.mapper = null;
    this.opacityScale = 1;
    this.modelScalePercent = DEFAULT_MODEL_SCALE_PERCENT;
    this.detailMode = "adaptive";
    this.lastDetailUpdate = 0;
    this.deferredLayers = new Set();
    this.projectModelBindings = {};
    this.generatedModelFactories = new Map();
    this.loadingModelFactories = new Set();
    this.zoneViewIndex = 0;
    this.selectedEntityId = null;
    window.__cadScene = this;
    this.init();
  }

  init() {
    // 提高环境光，让自发光材质颜色更饱和
    const ambient = new THREE.AmbientLight(0xffffff, 1.2);
    const directional = new THREE.DirectionalLight(0xffffff, 1.0);
    directional.position.set(50, 100, 50);
    const fill = new THREE.DirectionalLight(0x8899ff, 0.4);
    fill.position.set(-50, 30, -50);
    this.scene.add(ambient, directional, fill);
    this.resetGroups();
    this.setView("perspective");
    this.resize();
    window.addEventListener("resize", () => this.resize());
    this.renderer.domElement.addEventListener("pointerdown", (event) => this.pick(event));
    this.animate();
  }

  resetGroups() {
    Object.values(this.groups).forEach((g) => this.scene.remove(g));
    this._clearLabelDom();
    this.selectionRoot?.clear();
    this.clearMeasureGuides();
    this.groups = {
      shell:            new THREE.Group(), // 仓库建筑（地面+室内结构）
      'shell.outerWall':new THREE.Group(), // 仓库外墙
      vehicles:         new THREE.Group(), // 车辆月台
      'device.ap':      new THREE.Group(), // AP 设备
      'device.fisheye': new THREE.Group(), // 鱼眼设备
      'device.dome':    new THREE.Group(), // 半球设备
      'device.bullet':  new THREE.Group(), // 枪机设备
      'device.cabinet': new THREE.Group(), // 机柜设备
      'coverage.ap':    new THREE.Group(), // AP 覆盖圆
      'coverage.fisheye':new THREE.Group(),// 鱼眼覆盖圆
      'coverage.dome':  new THREE.Group(), // 半球覆盖
      'coverage.bullet':new THREE.Group(), // 枪机投射光锥
      cables:           new THREE.Group(), // 弱电线路
      'cables.cabinet': new THREE.Group(), // 机柜电缆
      'cables.spotlight':new THREE.Group(),// 射灯电缆
      spotlights:       new THREE.Group(), // 车尾射灯
      labels:           new THREE.Group(), // 对象标签
    };
    Object.entries(this.groups).forEach(([key, group]) => {
      group.visible = this.layerVisibility[key] ?? true;
      this.scene.add(group);
    });
  }

  _clearLabelDom() {
    const root = this.labelRenderer?.domElement;
    if (!root) return;
    root.querySelectorAll('[data-cad-label="true"], [data-measure-label="true"], .label').forEach((element) => element.remove());
  }

  _deviceGroupKey(type) {
    if (type === 'network.ap') return 'device.ap';
    if (type === 'security.camera.fisheye') return 'device.fisheye';
    if (type === 'security.camera.dome') return 'device.dome';
    if (type.startsWith('security.camera')) return 'device.bullet';
    if (type === 'network.cabinet' || type === 'network.switch' || type.startsWith('power.') || type === 'lighting.fixture') return 'device.cabinet';
    return 'device.bullet';
  }

  _coverageGroupKey(type) {
    if (type === 'network.ap') return 'coverage.ap';
    if (type === 'security.camera.fisheye') return 'coverage.fisheye';
    if (type === 'security.camera.dome') return 'coverage.dome';
    if (type.startsWith('security.camera')) return 'coverage.bullet';
    return null;
  }

  _bindingForDevice(device) {
    const type = device?.type || "";
    const binding = this.projectModelBindings?.[type];
    if (!binding?.threejs_module_code) return null;
    return binding;
  }

  _generatedModelForDevice(device) {
    const binding = this._bindingForDevice(device);
    if (!binding) return null;
    const key = binding.model_id || device.type;
    const createModel = this.generatedModelFactories.get(key);
    return createModel ? { binding, createModel } : null;
  }

  _preloadProjectModelBindings() {
    Object.values(this.projectModelBindings || {}).forEach((binding) => {
      if (!binding?.threejs_module_code) return;
      const key = binding.model_id || binding.model_name || binding.semantic_types?.[0];
      if (!key || this.generatedModelFactories.has(key) || this.loadingModelFactories.has(key)) return;
      this.loadingModelFactories.add(key);
      const blobUrl = URL.createObjectURL(new Blob([String(binding.threejs_module_code)], { type: "text/javascript" }));
      import(blobUrl)
        .then((module) => {
          const createModel = module.createModel || module.default;
          if (typeof createModel === "function") {
            this.generatedModelFactories.set(key, createModel);
            if (this.semantic) this.loadSemantic(this.semantic, { preserveView: true });
          } else {
            console.warn("[SceneBuilder] 项目模型绑定缺少 createModel:", key);
          }
        })
        .catch((error) => {
          console.error("[SceneBuilder] 项目模型绑定加载失败:", key, error);
        })
        .finally(() => {
          this.loadingModelFactories.delete(key);
          URL.revokeObjectURL(blobUrl);
        });
    });
  }

  loadSemantic(semantic, { preserveView = false } = {}) {
    this.semantic = semantic;
    this.deferredLayers = new Set();
    this.projectModelBindings = semantic.project?.model_bindings || {};
    this._preloadProjectModelBindings();

    // P1: 过滤坐标离群设备（IQR × 3 范围外的视为无效）
    const allDevices = semantic.devices || [];
    const filteredDevices = this._filterOutliers(allDevices);
    const cleanDevices = this.semantic?.drawing_meta?.source === "placement_studio"
      ? filteredDevices
      : this._applyLayoutCoverage(filteredDevices);
    const removedCount = allDevices.length - cleanDevices.length;
    if (removedCount > 0) console.warn(`[SceneBuilder] 过滤掉 ${removedCount} 个坐标异常设备`);

    // P2: 用干净设备 + 建筑结构坐标计算场景范围（而非图纸原始范围）
    const clusterExtents = this._sceneExtents(cleanDevices, semantic.structures || [], semantic.cables || [], semantic.areas || [], semantic.parking_spaces || [], semantic.fixtures || [], semantic.office_objects || []);
    this.mapper = new CoordMapper(clusterExtents);
    this.mapper.floorHeight = Number(semantic.site?.warehouse_floor_height_m || semantic.site?.dock_height_m || 0);
    this.mapper.warehouseHeight = Number(semantic.site?.warehouse_wall_height_m || 10.5);
    this.mapper.roofPeakHeight = Number(semantic.site?.warehouse_roof_peak_height_m || this.mapper.warehouseHeight);

    // P3: 根据场景宽度动态计算图标尺寸（场景的 1.2%）
    const sceneSpan = Math.max(this.mapper.width, this.mapper.depth);
    this.iconScale = Math.max(1.5, sceneSpan * 0.012);
    this.resetGroups();
    this.groups.shell.add(this.areaRenderer.renderShell(this.mapper));
    if ((semantic.structures || []).length > 0) {
      const structureBuckets = this._structureBuckets(semantic.structures || []);
      if (structureBuckets.inner.length) this.groups.shell.add(this.areaRenderer.renderStructures(structureBuckets.inner, this.mapper));
      if (structureBuckets.outerWall.length) this.groups["shell.outerWall"].add(this.areaRenderer.renderStructures(structureBuckets.outerWall, this.mapper));
    }
    if ((semantic.areas || []).length > 0) {
      const allAreas = semantic.areas || [];
      const liftAreas = allAreas.filter((area) => area.type === "area.lift_platform");
      const vehicleAreas = allAreas.filter((area) => area.type === "area.dock_platform" || area.type === "area.parking_yard");
      const outerWallAreas = allAreas.filter((area) => area.type === "area.warehouse.shell");
      const floorAreas = allAreas.filter((area) => !["area.lift_platform", "area.warehouse.shell", "area.dock_platform", "area.parking_yard"].includes(area.type));
      if (outerWallAreas.length) this.groups["shell.outerWall"].add(this.areaRenderer.renderAreas(outerWallAreas, this.mapper));
      if (floorAreas.length) this.groups.shell.add(this.areaRenderer.renderAreas(floorAreas, this.mapper));
      if (liftAreas.length) this.groups.vehicles.add(this.areaRenderer.renderAreas(liftAreas, this.mapper));
      if (vehicleAreas.length) this.groups.vehicles.add(this.areaRenderer.renderAreas(vehicleAreas, this.mapper));
    }
    if ((semantic.office_objects || []).length > 0) {
      this.groups.shell.add(this.officeRenderer.render(semantic.office_objects, this.mapper));
    }
    const cableBuckets = this._cableBuckets(semantic.cables || []);
    if (this._layerEnabled("cables")) this.groups.cables.add(this.cableRenderer.render(cableBuckets.weakCurrent, this.mapper));
    else this.deferredLayers.add("cables");
    if (this._layerEnabled("cables.cabinet")) this.groups["cables.cabinet"].add(this.cableRenderer.render(cableBuckets.cabinet, this.mapper));
    else this.deferredLayers.add("cables.cabinet");
    if (this._layerEnabled("cables.spotlight")) this.groups["cables.spotlight"].add(this.cableRenderer.render(cableBuckets.spotlight, this.mapper));
    else this.deferredLayers.add("cables.spotlight");
    if ((semantic.parking_spaces || []).length > 0) {
      this.groups.vehicles.add(this.vehicleRenderer.render(semantic.parking_spaces, this.mapper));
    }
    const modelScaleMultiplier = this.modelScaleMultiplier();
    if ((semantic.fixtures || []).length > 0 && this._layerEnabled("spotlights")) {
      this.groups.spotlights.add(this.vehicleRenderer.renderSpotlights(semantic.fixtures, this.mapper, modelScaleMultiplier));
    } else if ((semantic.fixtures || []).length > 0) {
      this.deferredLayers.add("spotlights");
    }

    cleanDevices.forEach((device) => {
      try {
      const covKey = this._coverageGroupKey(device.type);
      const includeCoverage = covKey ? this._layerEnabled(covKey) : false;
      const includeLabel = this._layerEnabled("labels");
      if (covKey && !includeCoverage) this.deferredLayers.add(covKey);
      if (!includeLabel) this.deferredLayers.add("labels");

      const rendered = this.deviceFactory.create(device, this.mapper, this.iconScale, modelScaleMultiplier, {
        includeCoverage,
        generatedModel: this._generatedModelForDevice(device),
      });
      const devKey = this._deviceGroupKey(device.type);
      rendered.object.userData.entity = rendered.object.userData.entity || device;
      this.groups[devKey].add(rendered.object);
      if (rendered.coverage) {
        rendered.coverage.userData.lodKind = "coverage";
        rendered.coverage.userData.lodType = device.type || "";
        rendered.coverage.userData.entity = device;
        if (covKey) this.groups[covKey].add(rendered.coverage);
      }
      if (includeLabel) {
        const labelPosition = this.mapper.toVector3(device.geometry?.position, this.deviceFactory.labelHeightFor(device, modelScaleMultiplier));
        this.groups.labels.add(this._createLabel(device.label || device.id, labelPosition, device.type || "", device, devKey));
      }
      } catch (err) {
        console.error("[SceneBuilder] device render failed:", device?.id, device?.type, err);
      }
    });

    if (!this._layerEnabled("labels") && (semantic.areas || []).some((area) => this._shouldCreateAreaLabel(area))) {
      this.deferredLayers.add("labels");
    }

    if (this._layerEnabled("labels")) {
      (semantic.areas || []).forEach((area) => {
        if (area.type === "area.warehouse.shell") return;
        const center = this._areaCenter(area);
        if (!center) return;
        const attrs = area.attributes || {};
        const floorElevation = Number(attrs.floor_elevation_m || attrs.deck_height_m || 0);
        const absoluteHeight = attrs.absolute_elevation
          ? floorElevation + Number(attrs.height_m || 0.35) + 0.25
          : area.type === "area.lift_platform"
          ? Number(attrs.height_m || this.mapper.floorHeight || 0) + 0.25
          : floorElevation + Number(attrs.room_height_m || attrs.height_m || 0.5) + 0.25;
        if (!this._shouldCreateAreaLabel(area)) return;
        const labelPosition = this.mapper.toVector3(center, absoluteHeight);
        this.groups.labels.add(this._createLabel(area.label || area.id, labelPosition, area.type || "", area, this._labelLayerKey(area.type || "", area)));
      });
    }

    this._tagTowerFloorLayers();
    this._applyTowerFloorVisibility();

    this._applyDetailMode();
    if (!preserveView) this.fitCamera();
    this._updateAdaptiveDetail(true);
  }

  modelScaleMultiplier() {
    return Math.max(MIN_MODEL_SCALE_PERCENT / 100, Math.min(Number(this.modelScalePercent || DEFAULT_MODEL_SCALE_PERCENT) / 100, MAX_MODEL_SCALE_PERCENT / 100));
  }

  getModelScalePercent() {
    return this.modelScalePercent;
  }

  setModelScalePercent(value) {
    const numeric = Math.max(MIN_MODEL_SCALE_PERCENT, Math.min(Number(value) || DEFAULT_MODEL_SCALE_PERCENT, MAX_MODEL_SCALE_PERCENT));
    if (Math.abs(numeric - this.modelScalePercent) < 0.01) return;
    this.modelScalePercent = numeric;
    if (this.semantic) this.loadSemantic(this.semantic, { preserveView: true });
  }

  _cableBuckets(cables) {
    const buckets = { weakCurrent: [], cabinet: [], spotlight: [] };
    cables.forEach((cable) => {
      const role = cable.attributes?.layer_role || "";
      const type = cable.type || "";
      if (type === "cable.power" || type === "cable.lighting") {
        buckets.weakCurrent.push(cable);
      } else if (role === "cabinet_cable" || type === "cable.cabinet_power") {
        buckets.cabinet.push(cable);
      } else if (role === "spotlight_cable" || type === "cable.spotlight_power") {
        buckets.spotlight.push(cable);
      } else {
        buckets.weakCurrent.push(cable);
      }
    });
    return buckets;
  }

  _shouldCreateAreaLabel(area) {
    const type = String(area?.type || "");
    if (area?.attributes?.show_label === false) return false;
    return type !== "area.parking_yard" && type !== "area.dock_platform";
  }

  _structureBuckets(structures) {
    const buckets = { inner: [], outerWall: [] };
    structures.forEach((structure) => {
      if (this._isReferenceRoadStructure(structure)) return;
      if (this._isOuterWallStructure(structure)) {
        buckets.outerWall.push(structure);
      } else {
        buckets.inner.push(structure);
      }
    });
    return buckets;
  }

  _isOuterWallStructure(structure) {
    const type = String(structure?.type || "");
    if (type === "building.outline") return true;
    if (type !== "building.wall") return false;
    const attrs = structure.attributes || {};
    if (attrs.tower || attrs.floor_label || attrs.office_kind) return false;
    const source = String(attrs.source || attrs.source_kind || attrs.footprint_source || "");
    return !source.includes("office") && !source.includes("办公室");
  }

  _tagTowerFloorLayers() {
    Object.values(this.groups).forEach((group) => this._tagTowerFloorLayerRecursive(group, ""));
  }

  _tagTowerFloorLayerRecursive(object, inheritedKey = "") {
    const key = this._entityTowerFloorLayerKey(object.userData?.entity) || inheritedKey;
    if (key) object.userData.floorLayerKey = key;
    object.children?.forEach((child) => this._tagTowerFloorLayerRecursive(child, key));
  }

  _entityTowerFloorLayerKey(entity) {
    if (!entity) return "";
    const attrs = entity.attributes || {};
    const floorId = String(attrs.floor_id || "");
    const floorLabel = String(attrs.floor_label || "");
    const tower = String(attrs.tower || attrs.tower_label || "");
    const source = `${floorId} ${floorLabel} ${tower}`.toLowerCase();
    const isTowerEntity = Boolean(attrs.tower || attrs.tower_label) || /炮楼|gatehouse|southwest|northwest|level_[12]/i.test(source);
    if (!isTowerEntity) return "";
    let level = Number(attrs.level);
    if (!Number.isFinite(level) || level <= 0) {
      const elevation = Number(attrs.floor_elevation_m ?? attrs.install_floor_elevation_m ?? 0);
      if (/二层|2f|level_2|level2/.test(source) || elevation >= 3.0) level = 2;
      else if (/一层|1f|level_1|level1/.test(source) || Math.abs(elevation) < 3.0) level = 1;
    }
    if (Math.round(level) === 1) return "tower.level1";
    if (Math.round(level) === 2) return "tower.level2";
    return "";
  }

  _objectTowerFloorVisible(object) {
    const key = object?.userData?.floorLayerKey;
    if (!key) return true;
    return this.layerVisibility[key] ?? true;
  }

  _applyTowerFloorVisibility() {
    Object.values(this.groups).forEach((group) => {
      group.traverse((object) => {
        const key = object.userData?.floorLayerKey;
        if (!key) return;
        const visible = this.layerVisibility[key] ?? true;
        if (!visible) {
          object.visible = false;
          object.userData.floorLayerHidden = true;
        } else if (object.userData.floorLayerHidden) {
          object.visible = true;
          object.userData.floorLayerHidden = false;
        }
      });
    });
  }

  _isReferenceRoadStructure(structure) {
    const attrs = structure.attributes || {};
    const matchedLayer = String(attrs.matched_layer || structure.layer || "");
    if (structure.type === "building.road" && attrs.source_kind === "fallback_structure_layer") return true;
    return matchedLayer === "A-ROAD" || matchedLayer === "A-ROAD-CENTER" || matchedLayer === "A-ROAD-RED";
  }

  _applyDetailMode() {
    const adaptive = this.detailMode === "adaptive";
    Object.values(this.groups).forEach((group) => {
      group.traverse((object) => {
        if (object.isMesh || object.isLine || object.isLineSegments) {
          object.frustumCulled = adaptive;
        }
      });
    });
    this._updateAdaptiveDetail(true);
  }

  _showFullDetail() {
    const labelsVisible = this.layerVisibility.labels ?? true;
    if (this.groups.labels) {
      this.groups.labels.visible = labelsVisible;
      this.groups.labels.children.forEach((label) => {
        const visible = labelsVisible && this._labelSourceLayerVisible(label);
        const floorVisible = this._objectTowerFloorVisible(label);
        label.visible = visible && floorVisible;
        if (label.element) label.element.style.opacity = visible && floorVisible ? "1" : "0";
      });
    }
    COVERAGE_GROUPS.forEach((groupName) => {
      const group = this.groups[groupName];
      if (!group) return;
      const layerVisible = this.layerVisibility[groupName] ?? true;
      group.visible = layerVisible;
      group.traverse((object) => {
        if (!object.material) return;
        object.visible = layerVisible && this._objectTowerFloorVisible(object);
        this._applyMaterialOpacity(object, 1);
      });
    });
    DETAIL_MODEL_GROUPS.forEach((groupName) => {
      const group = this.groups[groupName];
      if (!group) return;
      const layerVisible = this.layerVisibility[groupName] ?? true;
      this._detailRoots(groupName).forEach((root) => {
        root.visible = layerVisible && this._objectTowerFloorVisible(root);
        root.traverse((object) => {
          if (object.material) this._applyMaterialOpacity(object, 1, this._usesGlobalOpacity(groupName));
        });
      });
    });
  }

  _createLabel(text, position, type = "", entity = null, layerKey = "") {
    const label = this.labelRendererFactory.create(text, position, type);
    label.userData = {
      lodKind: "label",
      lodType: type,
      layerKey: layerKey || this._labelLayerKey(type, entity),
      priority: this._labelPriority(type, entity),
      entity,
    };
    const floorKey = this._entityTowerFloorLayerKey(entity);
    if (floorKey) label.userData.floorLayerKey = floorKey;
    return label;
  }

  _labelLayerKey(type = "", entity = null) {
    if (type === "network.ap") return "device.ap";
    if (type === "security.camera.fisheye") return "device.fisheye";
    if (type === "security.camera.dome") return "device.dome";
    if (type.startsWith("security.camera")) return "device.bullet";
    if (type === "network.cabinet" || type === "network.switch" || type.startsWith("power.") || type === "lighting.fixture") return "device.cabinet";
    if (type === "area.lift_platform" || type === "area.dock_platform" || type === "area.parking_yard" || type.startsWith("parking.")) return "vehicles";
    if (type.startsWith("area.")) return "shell";
    if (entity?.type) return this._labelLayerKey(entity.type, null);
    return "";
  }

  _labelSourceLayerVisible(label) {
    const layerKey = label?.userData?.layerKey;
    if (!layerKey) return true;
    return this.layerVisibility[layerKey] ?? true;
  }

  _labelPriority(type = "", entity = null) {
    if (type === "network.cabinet" || entity?.attributes?.role === "office_aggregation_42u") return 4;
    if (type === "network.ap" || type === "area.office" || type === "area.office.mezzanine") return 3;
    if (type === "area.warehouse.shell" || type === "area.lift_platform") return 3;
    if (type === "security.camera.dome" || type === "security.camera.fisheye") return 2;
    if (type.startsWith("security.camera")) return 1;
    return 2;
  }

  _updateAdaptiveDetail(force = false) {
    if (!this.mapper || !this.camera || !this.controls) return;
    if (this.detailMode !== "adaptive") {
      if (force) this._showFullDetail();
      return;
    }
    const now = performance.now();
    if (!force && now - this.lastDetailUpdate < DETAIL_UPDATE_INTERVAL_MS) return;
    this.lastDetailUpdate = now;

    const span = Math.max(this.mapper.width || 0, this.mapper.depth || 0, 80);
    const cameraDistance = this.camera.position.distanceTo(this.controls.target);
    const closeView = cameraDistance < span * 0.9;
    const labelNear = closeView ? span * 0.34 : span * 0.46;
    const labelMid = closeView ? span * 0.50 : span * 0.62;
    const labelFar = closeView ? span * 0.72 : span * 0.86;
    const coverageNear = closeView ? span * 0.42 : span * 0.58;
    const coverageFar = closeView ? span * 0.72 : span * 0.92;
    const modelNear = closeView ? span * 0.30 : span * 0.42;
    const modelFar = closeView ? span * 0.54 : span * 0.68;

    this._updateLabelDetail(labelNear, labelMid, labelFar);
    this._updateCoverageDetail(coverageNear, coverageFar, closeView);
    this._updateModelDetail(modelNear, modelFar, closeView);
  }

  _focusDistance(object, position = new THREE.Vector3()) {
    object.getWorldPosition(position);
    const toTarget = position.distanceTo(this.controls.target);
    const toCamera = position.distanceTo(this.camera.position) * 0.65;
    return Math.min(toTarget, toCamera);
  }

  _screenFocus(object, position = new THREE.Vector3(), projected = new THREE.Vector3()) {
    object.getWorldPosition(position);
    projected.copy(position).project(this.camera);
    const inFront = projected.z >= -1 && projected.z <= 1;
    const radius = Math.hypot(projected.x, projected.y);
    return {
      radius,
      inFrame: inFront && Math.abs(projected.x) <= 1.08 && Math.abs(projected.y) <= 1.08,
    };
  }

  _updateLabelDetail(labelNear, labelMid, labelFar) {
    const labelsVisible = this.layerVisibility.labels ?? true;
    const temp = new THREE.Vector3();
    const projected = new THREE.Vector3();
    this.groups.labels?.children.forEach((label) => {
      const priority = Number(label.userData?.priority || 0);
      const distance = this._focusDistance(label, temp);
      const screen = this._screenFocus(label, temp, projected);
      const screenLimit = priority >= 4 ? 1.12 : priority >= 3 ? 0.96 : priority >= 2 ? 0.78 : 0.58;
      let visible = labelsVisible && this._labelSourceLayerVisible(label) && this._objectTowerFloorVisible(label);
      if (visible) {
        if (priority >= 4) visible = distance <= labelFar * 1.18;
        else if (priority >= 3) visible = distance <= labelFar;
        else if (priority >= 2) visible = distance <= labelMid;
        else visible = distance <= labelNear;
        visible = visible && screen.inFrame && screen.radius <= screenLimit;
      }
      label.visible = visible;
      if (label.element) {
        const fadeStart = priority >= 3 ? labelMid : labelNear;
        const fadeEnd = priority >= 3 ? labelFar : labelMid;
        const distanceFade = THREE.MathUtils.clamp(1 - (distance - fadeStart) / Math.max(fadeEnd - fadeStart, 1), 0.25, 1);
        const screenFade = THREE.MathUtils.clamp(1 - (screen.radius - screenLimit * 0.68) / Math.max(screenLimit * 0.32, 0.01), 0.25, 1);
        const fade = Math.min(distanceFade, screenFade);
        label.element.style.opacity = visible ? String(fade) : "0";
      }
    });
  }

  _updateCoverageDetail(coverageNear, coverageFar, closeView) {
    const temp = new THREE.Vector3();
    const projected = new THREE.Vector3();
    COVERAGE_GROUPS.forEach((groupName) => {
      const group = this.groups[groupName];
      if (!group) return;
      const layerVisible = this.layerVisibility[groupName] ?? true;
      group.traverse((object) => {
        if (!object.material) return;
        const distance = this._focusDistance(object, temp);
        const screen = this._screenFocus(object, temp, projected);
        let lodOpacity = 1;
        if (distance > coverageFar) {
          lodOpacity = closeView ? 0.08 : 0.14;
        } else if (distance > coverageNear) {
          lodOpacity = closeView ? 0.22 : 0.34;
        }
        if (!screen.inFrame || screen.radius > 1.0) {
          object.visible = false;
          return;
        }
        if (screen.radius > 0.78) {
          lodOpacity = Math.min(lodOpacity, closeView ? 0.05 : 0.10);
        } else if (screen.radius > 0.58) {
          lodOpacity = Math.min(lodOpacity, closeView ? 0.14 : 0.22);
        }
        object.visible = layerVisible && this._objectTowerFloorVisible(object);
        this._applyMaterialOpacity(object, lodOpacity);
      });
    });
  }

  _updateModelDetail(modelNear, modelFar, closeView) {
    const temp = new THREE.Vector3();
    const projected = new THREE.Vector3();
    DETAIL_MODEL_GROUPS.forEach((groupName) => {
      const layerVisible = this.layerVisibility[groupName] ?? true;
      this._detailRoots(groupName).forEach((root) => {
        const priority = this._modelPriority(root);
        const distance = this._focusDistance(root, temp);
        const screen = this._screenFocus(root, temp, projected);
        const screenLimit = priority >= 4 ? 1.06 : priority >= 3 ? 0.94 : priority >= 2 ? 0.78 : 0.62;
        const distanceLimit = priority >= 4 ? modelFar * 1.25 : priority >= 3 ? modelFar * 1.08 : priority >= 2 ? modelFar : modelNear;
        const entityId = root.userData?.entity?.id;
        const selected = Boolean(entityId) && (entityId === this.selectedEntityId || (this.selectedEntityIds || []).includes(entityId));
        const placementKept = this.semantic?.drawing_meta?.source === "placement_studio" || Boolean(root.userData?.entity?.attributes?.placement);
        const visible = layerVisible && this._objectTowerFloorVisible(root)
          && (selected || placementKept || (screen.inFrame && screen.radius <= screenLimit && distance <= distanceLimit));
        root.visible = visible;
        if (!visible) return;
        const distanceFade = THREE.MathUtils.clamp(1 - (distance - distanceLimit * 0.72) / Math.max(distanceLimit * 0.28, 1), 0.24, 1);
        const screenFade = THREE.MathUtils.clamp(1 - (screen.radius - screenLimit * 0.66) / Math.max(screenLimit * 0.34, 0.01), 0.24, 1);
        const lodOpacity = closeView ? Math.min(distanceFade, screenFade) : Math.max(0.55, Math.min(distanceFade, screenFade));
        root.traverse((object) => {
          if (object.material) this._applyMaterialOpacity(object, lodOpacity, this._usesGlobalOpacity(groupName));
        });
      });
    });
  }

  _detailRoots(groupName) {
    const group = this.groups[groupName];
    if (!group) return [];
    const roots = [];
    if (groupName.startsWith("device.")) {
      group.children.forEach((child) => roots.push(child));
      return roots;
    }
    group.traverse((object) => {
      if (object.userData?.selectable) roots.push(object);
    });
    return roots;
  }

  _modelPriority(root) {
    const entity = root.userData?.entity || {};
    const kind = root.userData?.kind || "";
    const type = entity.type || "";
    if (type === "network.cabinet" || type.startsWith("power.") || entity.attributes?.role === "office_aggregation_42u") return 4;
    if (type === "lighting.fixture") return 2;
    if (type === "network.ap") return 3;
    if (type === "security.camera.fisheye" || type === "security.camera.dome") return 2;
    if (kind === "fixture" || type === "lighting.floodlight") return 3;
    if (kind === "vehicle") return 1;
    if (kind === "parking") return 1;
    if (type.startsWith("security.camera")) return 1;
    return 2;
  }

  _usesGlobalOpacity(groupName) {
    return groupName === "vehicles" || groupName === "spotlights";
  }

  _applyLayoutCoverage(devices) {
    const aps = devices.filter((device) => device.type === "network.ap" && device.geometry?.position);
    if (!aps.length) return devices;

    const radii = new Map();
    aps.forEach((device) => {
      if (this._hasCadCoverageRadius(device)) return;
      const radius = this._layoutApRadius(device, aps);
      if (!radius) return;
      radii.set(device, radius);
    });
    if (!radii.size) return devices;

    return devices.map((device) => {
      const radius = radii.get(device);
      if (!radius) return device;
      const current = Number(device.coverage?.radius_m);
      return {
        ...device,
        coverage: { ...(device.coverage || {}), radius_m: radius },
        attributes: {
          ...(device.attributes || {}),
          coverage_radius_source: "layout_ap_spacing",
          ...(Number.isFinite(current) && current > 0 ? { coverage_radius_previous_m: current } : {}),
        },
      };
    });
  }

  _hasCadCoverageRadius(device) {
    const attrs = device.attributes || {};
    const source = attrs.coverage_radius_source || attrs.coverage_radius_source_kind;
    if (source === "cad_circle" || source === "cad_block_coverage_circle") return true;
    const radiusMm = Number(attrs.coverage_radius_source_radius_mm || 0);
    return Number.isFinite(radiusMm) && radiusMm > 0;
  }

  _layoutApRadius(device, aps) {
    const peers = aps.filter((peer) => peer !== device && this._sameApCoverageGroup(device, peer));
    const candidates = (peers.length ? peers : aps.filter((peer) => peer !== device))
      .map((peer) => this._deviceDistanceMeters(device, peer))
      .filter((distance) => Number.isFinite(distance) && distance > 1.5)
      .sort((a, b) => a - b);
    const limits = device.attributes?.zone === "office" ? AP_LAYOUT_RADIUS_LIMITS.office : AP_LAYOUT_RADIUS_LIMITS.warehouse;
    const rawRadius = candidates.length ? candidates[0] * AP_LAYOUT_SPACING_FACTOR : limits.fallback;
    return Number(THREE.MathUtils.clamp(rawRadius, limits.min, limits.max).toFixed(1));
  }

  _sameApCoverageGroup(left, right) {
    const leftAttrs = left.attributes || {};
    const rightAttrs = right.attributes || {};
    const leftZone = leftAttrs.zone || "warehouse";
    const rightZone = rightAttrs.zone || "warehouse";
    const leftFloor = Number(leftAttrs.floor_elevation_m || 0);
    const rightFloor = Number(rightAttrs.floor_elevation_m || 0);
    return leftZone === rightZone && Math.abs(leftFloor - rightFloor) < 0.2;
  }

  _deviceDistanceMeters(left, right) {
    const a = left.geometry?.position;
    const b = right.geometry?.position;
    if (!a || !b) return Number.POSITIVE_INFINITY;
    return Math.hypot(a.x - b.x, a.y - b.y) / 1000;
  }

  _applyMaterialOpacity(object, lodOpacity = 1, useOpacityScale = true) {
    const materials = Array.isArray(object.material) ? object.material : [object.material];
    materials.forEach((material) => {
      if (!material) return;
      if (material.userData.baseOpacity == null) {
        material.userData.baseOpacity = material.opacity == null ? 1 : material.opacity;
      }
      material.transparent = true;
      const globalOpacity = useOpacityScale ? this.opacityScale : 1;
      const opacity = Math.max(0.02, material.userData.baseOpacity * globalOpacity * lodOpacity);
      material.opacity = opacity;
      material.depthWrite = opacity >= 0.95;
      material.needsUpdate = true;
    });
  }

  // IQR×3 离群值过滤
  _filterOutliers(devices) {
    if (this.semantic?.drawing_meta?.source === "placement_studio") return devices;
    if (devices.length < 6) return devices;
    const xs = devices.map(d => d.geometry?.position?.x ?? 0).sort((a, b) => a - b);
    const ys = devices.map(d => d.geometry?.position?.y ?? 0).sort((a, b) => a - b);
    const n = xs.length;
    const q1x = xs[Math.floor(n * 0.25)], q3x = xs[Math.floor(n * 0.75)];
    const q1y = ys[Math.floor(n * 0.25)], q3y = ys[Math.floor(n * 0.75)];
    const iqrX = q3x - q1x, iqrY = q3y - q1y;
    const fence = 3.0;
    return devices.filter(d => {
      if (d.attributes?.placement) return true;
      const x = d.geometry?.position?.x ?? 0;
      const y = d.geometry?.position?.y ?? 0;
      return x >= q1x - iqrX * fence && x <= q3x + iqrX * fence
          && y >= q1y - iqrY * fence && y <= q3y + iqrY * fence;
    });
  }

  // 从干净设备计算场景范围（加 5% 边距）
  _clusterExtents(devices) {
    if (!devices.length) return { min: { x: 0, y: 0 }, max: { x: 10000, y: 10000 } };
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    devices.forEach(d => {
      const { x, y } = d.geometry?.position ?? {};
      if (x != null) { minX = Math.min(minX, x); maxX = Math.max(maxX, x); }
      if (y != null) { minY = Math.min(minY, y); maxY = Math.max(maxY, y); }
    });
    const padX = Math.max((maxX - minX) * 0.05, 5000);
    const padY = Math.max((maxY - minY) * 0.05, 5000);
    return { min: { x: minX - padX, y: minY - padY }, max: { x: maxX + padX, y: maxY + padY } };
  }

  _sceneExtents(devices, structures = [], cables = [], areas = [], parkingSpaces = [], fixtures = [], officeObjects = []) {
    const points = [];
    devices.forEach((device) => {
      if (device.geometry?.position) points.push(device.geometry.position);
    });
    structures.forEach((structure) => {
      const geometry = structure.geometry || {};
      if (geometry.center) points.push(geometry.center);
      (geometry.points || []).forEach((point) => points.push(point));
    });
    cables.forEach((cable) => {
      (cable.geometry?.points || []).forEach((point) => points.push(point));
    });
    areas.forEach((area) => {
      (area.geometry?.points || []).forEach((point) => points.push(point));
    });
    parkingSpaces.forEach((space) => {
      (space.geometry?.points || []).forEach((point) => points.push(point));
    });
    fixtures.forEach((fixture) => {
      if (fixture.geometry?.position) points.push(fixture.geometry.position);
    });
    officeObjects.forEach((item) => {
      if (item.geometry?.position) points.push(item.geometry.position);
      (item.geometry?.points || []).forEach((point) => points.push(point));
    });
    if (!points.length) return this._clusterExtents(devices);
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    points.forEach((point) => {
      minX = Math.min(minX, point.x);
      maxX = Math.max(maxX, point.x);
      minY = Math.min(minY, point.y);
      maxY = Math.max(maxY, point.y);
    });
    const padX = Math.max((maxX - minX) * 0.05, 5000);
    const padY = Math.max((maxY - minY) * 0.05, 5000);
    return { min: { x: minX - padX, y: minY - padY }, max: { x: maxX + padX, y: maxY + padY } };
  }

  setLayerVisibility(layer, visible) {
    const shouldBuildDeferred = visible && this.deferredLayers?.has(layer) && DEFERRED_DEVICE_LAYERS.has(layer) && this.semantic;
    this.layerVisibility[layer] = visible;
    if (shouldBuildDeferred) {
      this.loadSemantic(this.semantic, { preserveView: true });
      return;
    }
    if (this.groups[layer]) this.groups[layer].visible = visible;
    if (TOWER_FLOOR_LAYERS.has(layer)) this._applyTowerFloorVisibility();
    this._updateAdaptiveDetail(true);
  }

  _layerEnabled(layer) {
    return this.layerVisibility[layer] ?? true;
  }

  getDetailMode() {
    return this.detailMode;
  }

  setDetailMode(mode) {
    this.detailMode = DETAIL_MODES.has(mode) ? mode : "full";
    this._applyDetailMode();
  }

  setOpacity(value) {
    this.opacityScale = value / 100;
    [...COVERAGE_GROUPS, ...CABLE_GROUPS, "shell", "shell.outerWall", "vehicles", "spotlights"].forEach((name) => {
      this.groups[name]?.traverse((object) => {
        if (object.material) {
          this._applyMaterialOpacity(object, 1);
        }
      });
    });
    this._updateAdaptiveDetail(true);
  }

  fitCamera() {
    this.setView("perspective");
  }

  setView(view) {
    if (view === "tower") {
      this._setFocusedView(this._officeBounds() || this._globalBounds(), {
        minDistance: 34,
        distanceScale: 1.18,
        targetHeight: 4.2,
        direction: { x: 0.78, y: 0.58, z: 0.82 },
      });
      return { label: "炮楼视角" };
    }
    if (view === "rack") {
      this._setFocusedView(this._warehouseInteriorBounds(), {
        minDistance: 72,
        distanceScale: 0.58,
        targetHeight: 3.4,
        direction: { x: -0.88, y: 0.34, z: 0.44 },
      });
      return { label: "货架视角" };
    }
    if (view === "zone") {
      const zones = this._zoneBounds();
      if (!zones.length) {
        this._setFocusedView(this._warehouseInteriorBounds(), {
          minDistance: 72,
          distanceScale: 0.62,
          targetHeight: 3.8,
          direction: { x: 0.72, y: 0.48, z: 0.66 },
        });
        return { label: "分区视角" };
      }
      const index = this.zoneViewIndex % zones.length;
      this.zoneViewIndex = (this.zoneViewIndex + 1) % zones.length;
      this._setFocusedView(zones[index].bounds, {
        minDistance: 48,
        distanceScale: 0.82,
        targetHeight: 4.0,
        direction: { x: 0.72, y: 0.50, z: 0.70 },
      });
      return { label: `分区视角 ${index + 1}/${zones.length}` };
    }
    this._setGlobalView(view === "top" ? "top" : "perspective");
    return { label: view === "top" ? "俯视" : "透视" };
  }

  _setGlobalView(mode = "perspective") {
    const bounds = this._globalBounds();
    const span = Math.max(bounds.width, bounds.depth, 80);
    const floor = this.mapper?.floorHeight || 0;
    this.camera.far = Math.max(span * 8, 5000);
    this.camera.updateProjectionMatrix();
    if (mode === "top") {
      this.camera.position.set(bounds.cx, floor + span * 1.35, bounds.cz + 0.01);
      this.controls.target.set(bounds.cx, floor, bounds.cz);
    } else {
      this.camera.position.set(bounds.cx, floor + span * 0.55, bounds.cz + span * 0.55);
      this.controls.target.set(bounds.cx, floor, bounds.cz);
    }
    this.controls.update();
    this._updateAdaptiveDetail(true);
  }

  _setFocusedView(bounds, options = {}) {
    const safeBounds = this._expandBounds(bounds || this._globalBounds(), options.padding ?? null);
    const span = Math.max(safeBounds.width, safeBounds.depth, 24);
    const floor = this.mapper?.floorHeight || 0;
    const target = new THREE.Vector3(safeBounds.cx, floor + (options.targetHeight ?? 3), safeBounds.cz);
    const distance = Math.max(span * (options.distanceScale ?? 0.9), options.minDistance ?? 40);
    const direction = options.direction || { x: 0.75, y: 0.52, z: 0.75 };
    this.camera.far = Math.max(distance * 8, span * 8, 5000);
    this.camera.updateProjectionMatrix();
    this.camera.position.set(
      target.x + distance * direction.x,
      target.y + distance * direction.y,
      target.z + distance * direction.z,
    );
    this.controls.target.copy(target);
    this.controls.update();
    this._updateAdaptiveDetail(true);
  }

  _globalBounds() {
    const width = this.mapper?.width || 120;
    const depth = this.mapper?.depth || 80;
    return this._normalizeBounds({
      minX: -width / 2,
      maxX: width / 2,
      minZ: -depth / 2,
      maxZ: depth / 2,
    });
  }

  _officeBounds() {
    const areaBounds = (this.semantic?.areas || [])
      .filter((area) => area.type === "area.office" || area.type === "area.office.mezzanine")
      .map((area) => this._boundsFromPoints(area.geometry?.points || []));
    const officeObjectBounds = this._boundsFromPoints(
      (this.semantic?.office_objects || [])
        .flatMap((item) => item.geometry?.position ? [item.geometry.position] : (item.geometry?.points || []))
        .filter(Boolean),
    );
    const cabinetBounds = this._boundsFromPoints(
      (this.semantic?.devices || [])
        .filter((device) => device.attributes?.zone === "office" || device.attributes?.role === "office_aggregation_42u")
        .map((device) => device.geometry?.position)
        .filter(Boolean),
    );
    return this._expandBounds(this._mergeBounds([...areaBounds, officeObjectBounds, cabinetBounds]), 8);
  }

  _warehouseBounds() {
    const shell = (this.semantic?.areas || []).find((area) => area.type === "area.warehouse.shell");
    if (shell && shell.attributes?.inferred_from !== "dock_layout_subject") {
      return this._boundsFromPoints(shell.geometry?.points || []) || this._globalBounds();
    }
    const structurePoints = (this.semantic?.structures || [])
      .filter((structure) => !this._isReferenceRoadStructure(structure))
      .filter((structure) => structure.type === "building.wall" || structure.type === "building.outline" || structure.type === "building.zone")
      .flatMap((structure) => structure.geometry?.points || []);
    const objectPoints = [
      ...(this.semantic?.devices || []).map((device) => device.geometry?.position).filter(Boolean),
      ...(this.semantic?.parking_spaces || []).flatMap((space) => space.geometry?.points || []),
      ...(this.semantic?.fixtures || []).map((fixture) => fixture.geometry?.position).filter(Boolean),
      ...structurePoints,
    ];
    return this._boundsFromPoints(objectPoints) || this._boundsFromPoints(shell?.geometry?.points || []) || this._globalBounds();
  }

  _warehouseInteriorBounds() {
    const bounds = this._warehouseBounds();
    const widthPad = bounds.width * 0.14;
    const depthPad = bounds.depth * 0.12;
    return this._normalizeBounds({
      minX: bounds.minX + widthPad,
      maxX: bounds.maxX - widthPad,
      minZ: bounds.minZ + depthPad,
      maxZ: bounds.maxZ - depthPad,
    });
  }

  _zoneBounds() {
    const explicitZones = (this.semantic?.areas || [])
      .filter((area) => /zone|partition|fire/i.test(area.type || "") || /分区|防火/i.test(area.label || ""))
      .filter((area) => area.type !== "area.warehouse.shell")
      .map((area, index) => ({
        label: area.label || `分区 ${index + 1}`,
        bounds: this._expandBounds(this._boundsFromPoints(area.geometry?.points || []), 6),
      }))
      .filter((zone) => zone.bounds);
    if (explicitZones.length > 1) return explicitZones;

    const shellBounds = this._warehouseBounds();
    const warehouse = this._warehouseInteriorBounds();
    const longAxis = warehouse.depth >= warehouse.width ? "z" : "x";
    const longSpan = longAxis === "z" ? warehouse.depth : warehouse.width;
    const shellLongSpan = longAxis === "z" ? shellBounds.depth : shellBounds.width;
    const count = shellLongSpan > 160 ? 4 : 3;
    return Array.from({ length: count }, (_, index) => {
      const start = (longAxis === "z" ? warehouse.minZ : warehouse.minX) + (longSpan / count) * index;
      const end = (longAxis === "z" ? warehouse.minZ : warehouse.minX) + (longSpan / count) * (index + 1);
      const bounds = longAxis === "z"
        ? { minX: warehouse.minX, maxX: warehouse.maxX, minZ: start, maxZ: end }
        : { minX: start, maxX: end, minZ: warehouse.minZ, maxZ: warehouse.maxZ };
      return {
        label: `分区 ${index + 1}`,
        bounds: this._expandBounds(this._normalizeBounds(bounds), 5),
      };
    });
  }

  _boundsFromPoints(points) {
    if (!this.mapper || !points?.length) return null;
    let minX = Infinity;
    let maxX = -Infinity;
    let minZ = Infinity;
    let maxZ = -Infinity;
    points.forEach((point) => {
      if (!Number.isFinite(point?.x) || !Number.isFinite(point?.y)) return;
      const mapped = this.mapper.toXZ(point);
      minX = Math.min(minX, mapped.x);
      maxX = Math.max(maxX, mapped.x);
      minZ = Math.min(minZ, mapped.z);
      maxZ = Math.max(maxZ, mapped.z);
    });
    if (![minX, maxX, minZ, maxZ].every(Number.isFinite)) return null;
    return this._normalizeBounds({ minX, maxX, minZ, maxZ });
  }

  _mergeBounds(boundsList) {
    const valid = boundsList.filter(Boolean);
    if (!valid.length) return null;
    return this._normalizeBounds({
      minX: Math.min(...valid.map((bounds) => bounds.minX)),
      maxX: Math.max(...valid.map((bounds) => bounds.maxX)),
      minZ: Math.min(...valid.map((bounds) => bounds.minZ)),
      maxZ: Math.max(...valid.map((bounds) => bounds.maxZ)),
    });
  }

  _expandBounds(bounds, padding = null) {
    if (!bounds) return null;
    const pad = padding == null ? Math.max(bounds.width, bounds.depth) * 0.08 : padding;
    return this._normalizeBounds({
      minX: bounds.minX - pad,
      maxX: bounds.maxX + pad,
      minZ: bounds.minZ - pad,
      maxZ: bounds.maxZ + pad,
    });
  }

  _normalizeBounds(bounds) {
    const minSize = 8;
    let { minX, maxX, minZ, maxZ } = bounds;
    if (maxX < minX) [minX, maxX] = [maxX, minX];
    if (maxZ < minZ) [minZ, maxZ] = [maxZ, minZ];
    if (maxX - minX < minSize) {
      const center = (minX + maxX) / 2;
      minX = center - minSize / 2;
      maxX = center + minSize / 2;
    }
    if (maxZ - minZ < minSize) {
      const center = (minZ + maxZ) / 2;
      minZ = center - minSize / 2;
      maxZ = center + minSize / 2;
    }
    return {
      minX,
      maxX,
      minZ,
      maxZ,
      width: maxX - minX,
      depth: maxZ - minZ,
      cx: (minX + maxX) / 2,
      cz: (minZ + maxZ) / 2,
    };
  }

  semanticExtents(semantic) {
    const points = [];
    (semantic.devices || []).forEach((device) => {
      if (device.geometry?.position) points.push(device.geometry.position);
    });
    (semantic.cables || []).forEach((cable) => {
      (cable.geometry?.points || []).forEach((point) => points.push(point));
    });
    (semantic.areas || []).forEach((area) => {
      (area.geometry?.points || []).forEach((point) => points.push(point));
    });
    (semantic.parking_spaces || []).forEach((space) => {
      (space.geometry?.points || []).forEach((point) => points.push(point));
    });
    (semantic.fixtures || []).forEach((fixture) => {
      if (fixture.geometry?.position) points.push(fixture.geometry.position);
    });
    (semantic.office_objects || []).forEach((item) => {
      if (item.geometry?.position) points.push(item.geometry.position);
      (item.geometry?.points || []).forEach((point) => points.push(point));
    });
    if (!points.length) return null;
    let minX = Infinity;
    let minY = Infinity;
    let maxX = -Infinity;
    let maxY = -Infinity;
    points.forEach((point) => {
      minX = Math.min(minX, point.x);
      minY = Math.min(minY, point.y);
      maxX = Math.max(maxX, point.x);
      maxY = Math.max(maxY, point.y);
    });
    const padX = Math.max((maxX - minX) * 0.08, 10000);
    const padY = Math.max((maxY - minY) * 0.08, 10000);
    return {
      min: { x: minX - padX, y: minY - padY },
      max: { x: maxX + padX, y: maxY + padY },
    };
  }

  _areaCenter(area) {
    const points = area.geometry?.points || [];
    if (!points.length) return null;
    return {
      x: points.reduce((sum, point) => sum + point.x, 0) / points.length,
      y: points.reduce((sum, point) => sum + point.y, 0) / points.length,
    };
  }

  pickGround(event) {
    if (!this.mapper) return null;
    const rect = this.renderer.domElement.getBoundingClientRect();
    this.pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    this.pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
    this.raycaster.setFromCamera(this.pointer, this.camera);
    const plane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
    const hit = new THREE.Vector3();
    if (!this.raycaster.ray.intersectPlane(plane, hit)) return null;
    return this.mapper.fromWorld(hit);
  }

  pickEntity(event, options = {}) {
    const rect = this.renderer.domElement.getBoundingClientRect();
    this.pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    this.pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
    this.raycaster.setFromCamera(this.pointer, this.camera);
    const skipCoverage = options.skipCoverage !== false;
    const skipShell = options.skipShell !== false;
    const candidates = [
      this.groups["device.ap"],
      this.groups["device.fisheye"],
      this.groups["device.dome"],
      this.groups["device.bullet"],
      this.groups["device.cabinet"],
      this.groups.spotlights,
      this.groups.cables,
      this.groups["cables.cabinet"],
      this.groups["cables.spotlight"],
      this.groups.vehicles,
      this.groups.shell,
    ].filter((group) => group && group.visible);
    const hits = this.raycaster.intersectObjects(candidates, true);
    for (const hit of hits) {
      if (skipCoverage && this._isCoverageObject(hit.object)) continue;
      let current = hit.object;
      while (current) {
        if (!this._objectVisibleInHierarchy(current)) break;
        const entity = current.userData?.entity;
        const type = String(entity?.type || "");
        if (skipShell && type === "area.warehouse.shell") {
          current = current.parent;
          continue;
        }
        if (skipCoverage && current.userData?.kind === "coverage") {
          current = current.parent;
          continue;
        }
        if (current.userData?.selectable && entity && current.userData?.kind !== "coverage") {
          return { object: current, entity, kind: current.userData.kind || "device" };
        }
        current = current.parent;
      }
    }
    return null;
  }

  _isCoverageObject(object) {
    let current = object;
    while (current) {
      if (current.userData?.lodKind === "coverage") return true;
      current = current.parent;
    }
    return false;
  }

  findObjectByEntityId(entityId) {
    if (!entityId) return null;
    let found = null;
    Object.values(this.groups).forEach((group) => {
      if (found || !group) return;
      group.traverse((object) => {
        if (!found && object.userData?.entity?.id === entityId && object.userData?.kind !== "coverage") found = object;
      });
    });
    return found;
  }

  markSelected(entityOrList) {
    const list = (Array.isArray(entityOrList) ? entityOrList : (entityOrList ? [entityOrList] : [])).filter((item) => item?.id);
    this.selectionRoot.clear();
    this.selectedEntityId = list[0]?.id || null;
    this.selectedEntityIds = list.map((item) => item.id);
    if (!this.mapper || !list.length) return;
    list.forEach((entity) => this._addSelectionMarker(entity));
    this._updateAdaptiveDetail(true);
  }

  _addSelectionMarker(entity) {
    const object = this.findObjectByEntityId(entity.id);
    const height = Number(entity.attributes?.install_height_m || object?.position?.y || 0);
    const origin = object
      ? object.getWorldPosition(new THREE.Vector3())
      : this.mapper.toVector3(entity.geometry?.position || { x: 0, y: 0 }, height || 0.04);
    const x = origin.x;
    const z = origin.z;
    const lampY = Math.max(origin.y || 0, height || 0);
    const ringMat = new THREE.MeshBasicMaterial({ color: 0xf4b43a, side: THREE.DoubleSide, transparent: true, opacity: 0.95, depthTest: false });
    const ground = new THREE.Mesh(new THREE.RingGeometry(0.45, 0.62, 40), ringMat);
    ground.rotation.x = -Math.PI / 2;
    ground.position.set(x, 0.08, z);
    ground.renderOrder = 20;
    this.selectionRoot.add(ground);
    if (lampY > 0.3) {
      const air = new THREE.Mesh(new THREE.RingGeometry(0.28, 0.42, 32), ringMat.clone());
      air.rotation.x = -Math.PI / 2;
      air.position.set(x, lampY, z);
      air.renderOrder = 21;
      this.selectionRoot.add(air);
      const stem = new THREE.Line(
        new THREE.BufferGeometry().setFromPoints([
          new THREE.Vector3(x, 0.08, z),
          new THREE.Vector3(x, lampY, z),
        ]),
        new THREE.LineBasicMaterial({ color: 0xf4b43a, transparent: true, opacity: 0.85, depthTest: false }),
      );
      stem.renderOrder = 21;
      this.selectionRoot.add(stem);
    }
    if (object) object.visible = true;
  }

  clearMeasureGuides() {
    this.measureRoot?.traverse((object) => {
      if (object.element) object.element.remove();
    });
    this.measureRoot?.clear();
    this.measureParts = [];
  }

  _measureSpecs(entity, bounds) {
    const pos = entity.geometry?.position || entity.geometry?.center;
    if (!pos || !this.mapper || !bounds) return [];
    const height = Number(entity.attributes?.install_height_m || 0);
    const origin = this.mapper.toVector3(pos, height);
    const ground = this.mapper.toVector3(pos, 0);
    const fmt = (label, meters) => `${label} ${Number(meters).toFixed(2)} m`;
    return [
      { start: origin, end: this.mapper.toVector3({ x: bounds.minX, y: pos.y }, height), text: fmt("左", (Number(pos.x) - bounds.minX) / 1000) },
      { start: origin, end: this.mapper.toVector3({ x: bounds.maxX, y: pos.y }, height), text: fmt("右", (bounds.maxX - Number(pos.x)) / 1000) },
      { start: origin, end: this.mapper.toVector3({ x: pos.x, y: bounds.minY }, height), text: fmt("前", (Number(pos.y) - bounds.minY) / 1000) },
      { start: origin, end: this.mapper.toVector3({ x: pos.x, y: bounds.maxY }, height), text: fmt("后", (bounds.maxY - Number(pos.y)) / 1000) },
      { start: ground, end: origin, text: fmt("高", height) },
    ];
  }

  drawMeasureGuides(entity, bounds) {
    if (!entity || !this.mapper || !bounds) return;
    const specs = this._measureSpecs(entity, bounds);
    if (!specs.length) return;
    if (!this.measureParts?.length || this.measureParts.length !== specs.length) {
      this.clearMeasureGuides();
      this.measureParts = specs.map((spec) => this._addMeasureSegment(spec.start, spec.end, spec.text));
      return;
    }
    specs.forEach((spec, index) => this._updateMeasureSegment(this.measureParts[index], spec));
  }

  _measureSide(start, end) {
    const dir = end.clone().sub(start);
    if (dir.lengthSq() < 0.0001) return new THREE.Vector3(0.22, 0, 0);
    if (Math.abs(dir.y) > Math.abs(dir.x) + Math.abs(dir.z)) return new THREE.Vector3(0.22, 0, 0);
    return new THREE.Vector3(-dir.z, 0, dir.x).normalize().multiplyScalar(0.22);
  }

  _addMeasureSegment(start, end, text) {
    const lineMat = new THREE.LineBasicMaterial({ color: 0xf4b43a, transparent: true, opacity: 0.95, depthTest: false });
    const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints([start, end]), lineMat);
    line.renderOrder = 30;
    this.measureRoot.add(line);
    const side = this._measureSide(start, end);
    const tickA = new THREE.Line(new THREE.BufferGeometry().setFromPoints([start.clone().add(side), start.clone().sub(side)]), lineMat);
    const tickB = new THREE.Line(new THREE.BufferGeometry().setFromPoints([end.clone().add(side), end.clone().sub(side)]), lineMat);
    tickA.renderOrder = 30;
    tickB.renderOrder = 30;
    this.measureRoot.add(tickA, tickB);
    const labelEl = document.createElement("div");
    labelEl.className = "measure-line-label";
    labelEl.dataset.measureLabel = "true";
    labelEl.textContent = text;
    const label = new CSS2DObject(labelEl);
    label.position.copy(start.clone().lerp(end, 0.5));
    this.measureRoot.add(label);
    return { line, tickA, tickB, label };
  }

  _updateMeasureSegment(part, spec) {
    if (!part?.line || !spec) return;
    part.line.geometry.setFromPoints([spec.start, spec.end]);
    part.line.geometry.computeBoundingSphere();
    const side = this._measureSide(spec.start, spec.end);
    part.tickA.geometry.setFromPoints([spec.start.clone().add(side), spec.start.clone().sub(side)]);
    part.tickB.geometry.setFromPoints([spec.end.clone().add(side), spec.end.clone().sub(side)]);
    part.label.position.copy(spec.start.clone().lerp(spec.end, 0.5));
    if (part.label.element) part.label.element.textContent = spec.text;
  }

  findCoverageByEntityId(entityId) {
    if (!entityId) return null;
    const keys = ["coverage.ap", "coverage.fisheye", "coverage.dome", "coverage.bullet"];
    for (const key of keys) {
      const found = (this.groups[key]?.children || []).find((child) => child.userData?.entity?.id === entityId);
      if (found) return found;
    }
    return null;
  }

  _isDirectionalCamera(entity) {
    const type = entity?.type || "";
    if (!type.startsWith("security.camera")) return false;
    if (type === "security.camera.fisheye") return false;
    if (type === "security.camera.dome" && !(Number(entity.coverage?.length_m) > 0)) return false;
    return true;
  }

  cadYaw(angleDeg) {
    return Math.PI + THREE.MathUtils.degToRad(Number(angleDeg || 0));
  }

  syncPlacementVisual(entity) {
    if (!entity?.id || !this.mapper) return;
    const pos = entity.geometry?.position || entity.geometry?.center;
    if (!pos) return;
    const world = this.mapper.toVector3(pos, 0);
    const object = this.findObjectByEntityId(entity.id);
    if (object) {
      object.position.x = world.x;
      object.position.z = world.z;
      if (this._isDirectionalCamera(entity)) object.rotation.y = this.cadYaw(entity.orientation?.angle_deg);
    }
    const coverage = this.findCoverageByEntityId(entity.id);
    if (!coverage) return;
    if (coverage.userData.anchoredAtDevice) {
      coverage.position.x = world.x;
      coverage.position.z = world.z;
    } else {
      const base = coverage.userData.baseWorld || world;
      coverage.position.x = world.x - base.x;
      coverage.position.z = world.z - base.z;
    }
    if (this._isDirectionalCamera(entity)) coverage.rotation.y = this.cadYaw(entity.orientation?.angle_deg);
    if (entity.type === "network.ap") {
      const radius = Number(entity.coverage?.radius_m || entity.attributes?.coverage_radius_m || coverage.userData.baseRadius || 14);
      const factor = Math.max(0.15, radius / (coverage.userData.baseRadius || 14));
      coverage.traverse((child) => {
        if (child.userData?.coveragePart === "downlight_beam") {
          child.scale.x = factor;
          child.scale.z = factor;
        }
        if (child.userData?.animation === "ap_wifi_ripple") child.userData.radius = radius;
      });
    } else if (this._isDirectionalCamera(entity) && coverage.userData.baseLength) {
      const length = Number(entity.coverage?.length_m || coverage.userData.baseLength);
      const factor = Math.max(0.15, length / coverage.userData.baseLength);
      coverage.scale.x = factor;
      coverage.scale.z = factor;
    }
  }

  pick(event) {
    const picked = this.pickEntity(event);
    if (picked && this.onSelect) this.onSelect(picked.entity, picked.kind);
    return picked;
  }

  _objectVisibleInHierarchy(object) {
    let current = object;
    while (current) {
      if (current.visible === false) return false;
      current = current.parent;
    }
    return true;
  }

  resize() {
    const rect = this.container.getBoundingClientRect();
    this.camera.aspect = Math.max(rect.width, 1) / Math.max(rect.height, 1);
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(rect.width, rect.height, false);
    this.labelRenderer.setSize(rect.width, rect.height);
  }

  _updateCoverageAnimations(elapsedSeconds) {
    const apCoverage = this.groups["coverage.ap"];
    if (!apCoverage || !apCoverage.visible) return;
    const opacityScale = this.opacityScale ?? 1;
    apCoverage.traverse((object) => {
      if (object.userData?.animation !== "ap_wifi_ripple" || !object.material) return;
      const radius = Number(object.userData.radius || 1);
      const phase = Number(object.userData.phase || 0);
      const speed = Number(object.userData.speed || 0.18);
      const progress = (elapsedSeconds * speed + phase) % 1;
      const scale = radius * (0.22 + progress * 0.78);
      const baseOpacity = Number(object.userData.baseOpacity || object.material.userData.baseOpacity || 0.26);
      object.scale.set(scale, scale, 1);
      object.material.opacity = Math.max(0.02, baseOpacity * (1 - progress) * opacityScale);
      object.material.needsUpdate = true;
    });
  }

  animate() {
    requestAnimationFrame(() => this.animate());
    const elapsedSeconds = this.animationClock.getElapsedTime();
    this.controls.update();
    this._updateAdaptiveDetail();
    this._updateCoverageAnimations(elapsedSeconds);
    if (this.groups.labels) {
      this.groups.labels.visible = this.layerVisibility.labels ?? true;
    }
    this.renderer.render(this.scene, this.camera);
    this.labelRenderer.render(this.scene, this.camera);
  }
}

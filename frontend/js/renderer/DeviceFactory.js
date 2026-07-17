import * as THREE from "three";

const COLORS = {
  fisheye: 0xff8a1c,
  fisheyeDark: 0xfff2cc,
  fisheyeLens: 0x7dd3fc,
  dome: 0xb79cff,
  bullet: 0xff4d4d,
  ap: 0x22d3ee,
  cabinet: 0x5aa6c8,
  cabinetDark: 0x15323d,
  ups: 0x2dd4bf,
  upsDark: 0x102827,
  battery: 0xfbbf24,
  batteryDark: 0x2a2110,
  maintenance: 0x7ddc83,
  white: 0xeaf4f5,
  black: 0x101315,
  glass: 0x172530,
  metal: 0x9aa6a8,
  generic: 0xffaa00,
};

const CABINET_DIMENSIONS = {
  42: { width: 0.72, depth: 0.56, height: 2.05 },
  22: { width: 0.62, depth: 0.48, height: 1.08 },
  12: { width: 0.50, depth: 0.36, height: 0.64 },
  9: { width: 0.44, depth: 0.32, height: 0.50 },
  ups: { width: 0.68, depth: 0.54, height: 1.18 },
  battery: { width: 0.74, depth: 0.56, height: 1.04 },
};
const DEFAULT_DEVICE_MODEL_SCALE = 2.0;
const MIN_DEVICE_MODEL_SCALE = 1.0;
const MAX_DEVICE_MODEL_SCALE = 3.0;
const DEVICE_VISUAL_SIZE_BOOST = 2.0;
const CABINET_VISUAL_SIZE_BOOST = 2.0;
const CABINET_VISUAL_SCALE = 1.15;
const FLOOR_CABINET_VISUAL_SCALE = 1.0;
const DEFAULT_MAINTENANCE_CLEARANCE_M = 0.15;
const PROJECTED_COVERAGE_OPACITY = {
  ap: 0.34,
  fisheye: 0.36,
  dome: 0.30,
  bullet: 0.26,
};
const AP_WIFI_RIPPLE_COUNT = 3;
const AP_WIFI_RIPPLE_OPACITY = 0.26;
const AP_WIFI_RIPPLE_SPEED = 0.18;

function material(color, options = {}) {
  const opacity = options.opacity ?? 1;
  return new THREE.MeshStandardMaterial({
    color,
    roughness: options.roughness ?? 0.58,
    metalness: options.metalness ?? 0.04,
    transparent: options.transparent ?? opacity < 1,
    opacity,
    side: THREE.DoubleSide,
    depthWrite: opacity >= 0.95,
  });
}

function addSmallLabelPlate(group, y, width, depth, color) {
  const plate = new THREE.Mesh(
    new THREE.BoxGeometry(width, 0.012, depth),
    material(color, { roughness: 0.65 }),
  );
  plate.position.set(0, y, -depth * 0.55);
  group.add(plate);
}

function yawFromCadAngle(angleDeg) {
  return Math.PI + THREE.MathUtils.degToRad(Number(angleDeg || 0));
}

export class DeviceFactory {
  create(device, mapper, iconScale = 5, modelScaleMultiplier = DEFAULT_DEVICE_MODEL_SCALE, options = {}) {
    const pos2d = device.geometry?.position;
    if (!pos2d) return { object: new THREE.Group(), coverage: null };

    const visualScale = this._visualScale(modelScaleMultiplier);
    const baseScale = Math.max(0.9, Math.min(iconScale * 0.42, 1.6));
    const modelScale = baseScale * visualScale * DEVICE_VISUAL_SIZE_BOOST;
    const origin = mapper.toVector3(pos2d, 0);

    const group = new THREE.Group();
    group.position.copy(origin);
    group.userData = { selectable: true, entity: device, kind: "device" };

    const body = this._makeGeneratedBody(device, modelScale, options.generatedModel) || this._makeBody(device, modelScale, visualScale);
    group.add(body);

    const directionalDome = device.type === "security.camera.dome" && Number(device.coverage?.length_m || 0) > 0;
    if (
      device.orientation?.angle_deg != null &&
      (device.type || "").startsWith("security.camera") &&
      (directionalDome || !["security.camera.fisheye", "security.camera.dome"].includes(device.type))
    ) {
      group.rotation.y = yawFromCadAngle(device.orientation.angle_deg);
    }

    const coverage = options.includeCoverage === false ? null : this._makeCoverage(device, mapper, modelScale);
    return { object: group, coverage };
  }

  _makeGeneratedBody(device, modelScale, generatedModel) {
    const createModel = generatedModel?.createModel;
    const binding = generatedModel?.binding || {};
    if (typeof createModel !== "function") return null;
    try {
      const parameters = binding.parameters || {};
      const colors = parameters.preview_overrides || {};
      const object = createModel({
        THREE,
        entity: device,
        scale: modelScale,
        colors: {
          primary: colors.primary_color || colors.primary || "#eaf4f5",
          primary_color: colors.primary_color || colors.primary || "#eaf4f5",
          accent: colors.accent_color || colors.accent || "#22d3ee",
          accent_color: colors.accent_color || colors.accent || "#22d3ee",
          rim: colors.rim || "#b8d7dc",
          outline: colors.outline || "#073b43",
        },
        dimensions: parameters,
      });
      if (!object) return null;
      const wrapper = new THREE.Group();
      wrapper.name = `project_bound_${binding.model_id || device.type || "device"}`;
      wrapper.userData = {
        generatedModel: true,
        locked: Boolean(binding.locked),
        modelId: binding.model_id,
        modelName: binding.model_name,
      };
      wrapper.add(object);
      wrapper.position.y = this.installHeightFor(device);
      return wrapper;
    } catch (error) {
      console.error("[DeviceFactory] project-bound model failed:", binding.model_id || device.type, error);
      return null;
    }
  }

  _makeBody(device, scale, visualScale) {
    const type = device.type || "";
    if (type === "network.ap") return this._makeAp(device, scale);
    if (type === "security.camera.fisheye") return this._makeFisheye(device, scale);
    if (type === "security.camera.dome") return this._makeDome(device, scale);
    if (type.startsWith("security.camera")) return this._makeBullet(device, scale);
    if (type === "network.cabinet") return this._makeCabinet(device, visualScale);
    return this._makeGeneric(device, scale);
  }

  _makeAp(device, scale) {
    const group = new THREE.Group();
    const height = this.installHeightFor(device);

    const shell = new THREE.Mesh(
      new THREE.CylinderGeometry(0.36 * scale, 0.34 * scale, 0.08 * scale, 32),
      material(COLORS.white, { roughness: 0.42 }),
    );
    shell.position.y = height;
    group.add(shell);

    const topDot = new THREE.Mesh(
      new THREE.CylinderGeometry(0.10 * scale, 0.10 * scale, 0.018 * scale, 24),
      material(COLORS.ap, { roughness: 0.34, metalness: 0.02 }),
    );
    topDot.position.y = height + 0.048 * scale;
    group.add(topDot);

    const topBarMaterial = material(COLORS.ap, { roughness: 0.42, metalness: 0.02 });
    for (const rotation of [0, Math.PI / 2]) {
      const bar = new THREE.Mesh(new THREE.BoxGeometry(0.58 * scale, 0.016 * scale, 0.060 * scale), topBarMaterial);
      bar.position.y = height + 0.060 * scale;
      bar.rotation.y = rotation;
      group.add(bar);
    }

    const ring = new THREE.Mesh(
      new THREE.TorusGeometry(0.24 * scale, 0.018 * scale, 12, 42),
      material(COLORS.ap, { roughness: 0.5 }),
    );
    ring.rotation.x = Math.PI / 2;
    ring.position.y = height - 0.052 * scale;
    group.add(ring);
    return group;
  }

  _makeFisheye(device, scale) {
    const group = new THREE.Group();
    const height = this.installHeightFor(device);

    const mount = new THREE.Mesh(
      new THREE.CylinderGeometry(0.40 * scale, 0.42 * scale, 0.08 * scale, 42),
      material(COLORS.fisheyeDark, { roughness: 0.48, metalness: 0.06 }),
    );
    mount.position.y = height;
    group.add(mount);

    const topLens = new THREE.Mesh(
      new THREE.CylinderGeometry(0.18 * scale, 0.18 * scale, 0.020 * scale, 32),
      material(COLORS.fisheyeLens, { transparent: true, opacity: 0.94, roughness: 0.12, metalness: 0.16 }),
    );
    topLens.position.y = height + 0.052 * scale;
    group.add(topLens);

    const topRing = new THREE.Mesh(
      new THREE.TorusGeometry(0.28 * scale, 0.018 * scale, 12, 42),
      material(COLORS.fisheye, { roughness: 0.38, metalness: 0.04 }),
    );
    topRing.rotation.x = Math.PI / 2;
    topRing.position.y = height + 0.064 * scale;
    group.add(topRing);

    const face = new THREE.Mesh(
      new THREE.CylinderGeometry(0.34 * scale, 0.36 * scale, 0.055 * scale, 42),
      material(COLORS.fisheye, { roughness: 0.36, metalness: 0.04 }),
    );
    face.position.y = height - 0.055 * scale;
    group.add(face);

    const lens = new THREE.Mesh(
      new THREE.SphereGeometry(0.23 * scale, 28, 14),
      material(COLORS.fisheyeLens, { transparent: true, opacity: 0.92, roughness: 0.12, metalness: 0.16 }),
    );
    lens.scale.y = 0.46;
    lens.position.y = height - 0.095 * scale;
    group.add(lens);

    const lensRing = new THREE.Mesh(
      new THREE.TorusGeometry(0.26 * scale, 0.020 * scale, 12, 42),
      material(COLORS.white, { roughness: 0.5 }),
    );
    lensRing.rotation.x = Math.PI / 2;
    lensRing.position.y = height - 0.083 * scale;
    group.add(lensRing);

    const tabMaterial = material(COLORS.fisheye, { roughness: 0.42, metalness: 0.04 });
    for (let index = 0; index < 4; index += 1) {
      const tab = new THREE.Mesh(new THREE.BoxGeometry(0.12 * scale, 0.035 * scale, 0.34 * scale), tabMaterial);
      tab.position.y = height - 0.045 * scale;
      tab.rotation.y = index * Math.PI / 2;
      tab.position.x = Math.sin(tab.rotation.y) * 0.34 * scale;
      tab.position.z = Math.cos(tab.rotation.y) * 0.34 * scale;
      group.add(tab);
    }
    return group;
  }

  _makeDome(device, scale) {
    const group = new THREE.Group();
    const height = this.installHeightFor(device);

    const mount = new THREE.Mesh(
      new THREE.CylinderGeometry(0.34 * scale, 0.36 * scale, 0.10 * scale, 42),
      material(COLORS.white, { roughness: 0.38, metalness: 0.03 }),
    );
    mount.position.y = height + 0.035 * scale;
    group.add(mount);

    const topWindow = new THREE.Mesh(
      new THREE.CylinderGeometry(0.165 * scale, 0.165 * scale, 0.014 * scale, 32),
      material(COLORS.glass, { transparent: true, opacity: 0.88, roughness: 0.18, metalness: 0.12 }),
    );
    topWindow.position.y = height + 0.092 * scale;
    group.add(topWindow);

    const topRing = new THREE.Mesh(
      new THREE.TorusGeometry(0.190 * scale, 0.014 * scale, 12, 36),
      material(COLORS.metal, { roughness: 0.42, metalness: 0.18 }),
    );
    topRing.rotation.x = Math.PI / 2;
    topRing.position.y = height + 0.102 * scale;
    group.add(topRing);

    const topLens = new THREE.Mesh(
      new THREE.CylinderGeometry(0.055 * scale, 0.055 * scale, 0.016 * scale, 20),
      material(COLORS.black, { roughness: 0.16, metalness: 0.14 }),
    );
    topLens.position.set(0, height + 0.112 * scale, -0.045 * scale);
    group.add(topLens);

    const housing = new THREE.Mesh(
      new THREE.CylinderGeometry(0.31 * scale, 0.26 * scale, 0.16 * scale, 42),
      material(COLORS.white, { roughness: 0.44, metalness: 0.02 }),
    );
    housing.position.y = height - 0.065 * scale;
    group.add(housing);

    const trim = new THREE.Mesh(
      new THREE.TorusGeometry(0.265 * scale, 0.020 * scale, 12, 42),
      material(COLORS.white, { roughness: 0.5, metalness: 0.03 }),
    );
    trim.rotation.x = Math.PI / 2;
    trim.position.y = height - 0.145 * scale;
    group.add(trim);

    const glass = new THREE.Mesh(
      new THREE.SphereGeometry(0.245 * scale, 32, 16),
      material(COLORS.glass, { transparent: true, opacity: 0.72, roughness: 0.16, metalness: 0.12 }),
    );
    glass.scale.y = 0.62;
    glass.position.y = height - 0.185 * scale;
    group.add(glass);

    const gimbal = new THREE.Mesh(
      new THREE.SphereGeometry(0.105 * scale, 20, 12),
      material(COLORS.black, { roughness: 0.24, metalness: 0.1 }),
    );
    gimbal.scale.y = 0.72;
    gimbal.position.set(0, height - 0.175 * scale, -0.095 * scale);
    group.add(gimbal);

    const lens = new THREE.Mesh(
      new THREE.CylinderGeometry(0.042 * scale, 0.042 * scale, 0.020 * scale, 18),
      material(COLORS.fisheyeLens, { transparent: true, opacity: 0.9, roughness: 0.1, metalness: 0.18 }),
    );
    lens.rotation.x = Math.PI / 2;
    lens.position.set(0, height - 0.176 * scale, -0.190 * scale);
    group.add(lens);

    const screwMaterial = material(COLORS.generic, { roughness: 0.52, metalness: 0.08 });
    for (const angle of [0, (Math.PI * 2) / 3, (Math.PI * 4) / 3]) {
      const screw = new THREE.Mesh(new THREE.BoxGeometry(0.045 * scale, 0.018 * scale, 0.070 * scale), screwMaterial);
      screw.position.set(Math.sin(angle) * 0.30 * scale, height - 0.090 * scale, Math.cos(angle) * 0.30 * scale);
      screw.rotation.y = angle;
      group.add(screw);
    }

    return group;
  }

  _makeBullet(device, scale) {
    const group = new THREE.Group();
    const height = this.installHeightFor(device);

    const bracket = new THREE.Mesh(
      new THREE.CylinderGeometry(0.035 * scale, 0.035 * scale, 0.42 * scale, 10),
      material(COLORS.bullet, { roughness: 0.5 }),
    );
    bracket.position.y = height - 0.24 * scale;
    group.add(bracket);

    const body = new THREE.Mesh(
      new THREE.CylinderGeometry(0.11 * scale, 0.11 * scale, 0.62 * scale, 18),
      material(COLORS.white, { roughness: 0.36 }),
    );
    body.rotation.x = Math.PI / 2;
    body.position.set(0, height, -0.22 * scale);
    group.add(body);

    const shade = new THREE.Mesh(
      new THREE.BoxGeometry(0.34 * scale, 0.10 * scale, 0.72 * scale),
      material(COLORS.bullet, { roughness: 0.48 }),
    );
    shade.position.set(0, height + 0.11 * scale, -0.23 * scale);
    group.add(shade);

    const lens = new THREE.Mesh(
      new THREE.CylinderGeometry(0.075 * scale, 0.075 * scale, 0.035 * scale, 18),
      material(COLORS.black, { roughness: 0.2, metalness: 0.12 }),
    );
    lens.rotation.x = Math.PI / 2;
    lens.position.set(0, height, -0.56 * scale);
    group.add(lens);
    return group;
  }

  _makeCabinet(device, visualScale = DEFAULT_DEVICE_MODEL_SCALE) {
    const attrs = device.attributes || {};
    const role = this._cabinetRole(device);
    if (role === "ups_power") return this._makeUpsCabinet(device, visualScale);
    if (role === "ups_battery") return this._makeBatteryCabinet(device, visualScale);
    const rackUnits = Number(attrs.rack_units || this._rackUnitsFromLabel(device.label) || 12);
    const baseDimensions = CABINET_DIMENSIONS[rackUnits] || CABINET_DIMENSIONS[12];
    const dimensions = this._cabinetVisualDimensions(baseDimensions, visualScale, { floorEquipment: attrs.mount !== "wall" });
    const group = new THREE.Group();
    const topEdge = Number(attrs.top_edge_height_m || 0);
    const floorElevation = Number(attrs.floor_elevation_m || 0);
    const y = attrs.mount === "wall" && topEdge > 0
      ? floorElevation + Math.max(topEdge - dimensions.height / 2, dimensions.height / 2)
      : floorElevation + dimensions.height / 2;
    if (attrs.mount !== "wall" && attrs.maintenance_clearance_m) {
      this._addMaintenanceFootprint(group, device, dimensions, COLORS.maintenance);
    }

    const shell = new THREE.Mesh(
      new THREE.BoxGeometry(dimensions.width, dimensions.height, dimensions.depth),
      material(COLORS.cabinet, { roughness: 0.5, metalness: 0.08 }),
    );
    shell.position.y = y;
    group.add(shell);

    const door = new THREE.Mesh(
      new THREE.BoxGeometry(dimensions.width * 0.82, dimensions.height * 0.78, 0.018),
      material(COLORS.cabinetDark, { roughness: 0.62, metalness: 0.04 }),
    );
    door.position.set(0, y, -dimensions.depth / 2 - 0.012);
    group.add(door);

    const ventCount = Math.max(2, Math.min(6, Math.round(rackUnits / 8)));
    for (let i = 0; i < ventCount; i += 1) {
      const ventY = y + dimensions.height * (0.28 - i * 0.11);
      addSmallLabelPlate(group, ventY, dimensions.width * 0.52, 0.022, COLORS.white);
    }

    if (attrs.mount === "wall") {
      const bracket = new THREE.Mesh(
        new THREE.BoxGeometry(dimensions.width * 1.08, 0.04, 0.06),
        material(COLORS.metal, { roughness: 0.44, metalness: 0.25 }),
      );
      bracket.position.set(0, y - dimensions.height / 2 - 0.05, dimensions.depth / 2 + 0.04);
      group.add(bracket);
    }
    return group;
  }

  _makeUpsCabinet(device, visualScale = DEFAULT_DEVICE_MODEL_SCALE) {
    const dimensions = this._cabinetVisualDimensions(CABINET_DIMENSIONS.ups, visualScale, { floorEquipment: true });
    const y = this._floorCabinetY(device, dimensions.height);
    const group = new THREE.Group();
    this._addMaintenanceFootprint(group, device, dimensions, COLORS.ups);

    const shell = new THREE.Mesh(
      new THREE.BoxGeometry(dimensions.width, dimensions.height, dimensions.depth),
      material(COLORS.upsDark, { roughness: 0.5, metalness: 0.06 }),
    );
    shell.position.y = y;
    group.add(shell);

    const face = new THREE.Mesh(
      new THREE.BoxGeometry(dimensions.width * 0.84, dimensions.height * 0.82, 0.018),
      material(COLORS.ups, { roughness: 0.48, metalness: 0.08 }),
    );
    face.position.set(0, y, -dimensions.depth / 2 - 0.012);
    group.add(face);

    const screen = new THREE.Mesh(
      new THREE.BoxGeometry(dimensions.width * 0.42, dimensions.height * 0.16, 0.024),
      material(0x0b1618, { roughness: 0.22, metalness: 0.02 }),
    );
    screen.position.set(0, y + dimensions.height * 0.22, -dimensions.depth / 2 - 0.028);
    group.add(screen);

    for (let index = 0; index < 3; index += 1) {
      addSmallLabelPlate(group, y + dimensions.height * (0.02 - index * 0.12), dimensions.width * 0.58, 0.018, COLORS.white);
    }
    return group;
  }

  _makeBatteryCabinet(device, visualScale = DEFAULT_DEVICE_MODEL_SCALE) {
    const dimensions = this._cabinetVisualDimensions(CABINET_DIMENSIONS.battery, visualScale, { floorEquipment: true });
    const y = this._floorCabinetY(device, dimensions.height);
    const group = new THREE.Group();
    this._addMaintenanceFootprint(group, device, dimensions, COLORS.battery);

    const shell = new THREE.Mesh(
      new THREE.BoxGeometry(dimensions.width, dimensions.height, dimensions.depth),
      material(COLORS.batteryDark, { roughness: 0.54, metalness: 0.04 }),
    );
    shell.position.y = y;
    group.add(shell);

    const door = new THREE.Mesh(
      new THREE.BoxGeometry(dimensions.width * 0.86, dimensions.height * 0.84, 0.018),
      material(COLORS.battery, { roughness: 0.5, metalness: 0.03 }),
    );
    door.position.set(0, y, -dimensions.depth / 2 - 0.012);
    group.add(door);

    const cellMaterial = material(0xfff1b8, { roughness: 0.45, metalness: 0.02 });
    for (let row = 0; row < 3; row += 1) {
      for (let col = 0; col < 2; col += 1) {
        const cell = new THREE.Mesh(
          new THREE.BoxGeometry(dimensions.width * 0.24, dimensions.height * 0.13, 0.026),
          cellMaterial,
        );
        cell.position.set(
          dimensions.width * (-0.16 + col * 0.32),
          y + dimensions.height * (0.22 - row * 0.18),
          -dimensions.depth / 2 - 0.03,
        );
        group.add(cell);
      }
    }
    return group;
  }

  _makeGeneric(device, scale) {
    const height = this.installHeightFor(device);
    const group = new THREE.Group();
    const marker = new THREE.Mesh(
      new THREE.SphereGeometry(0.24 * scale, 14, 10),
      material(COLORS.generic),
    );
    marker.position.y = height || 0.25;
    group.add(marker);
    return group;
  }

  labelHeightFor(device, modelScaleMultiplier = DEFAULT_DEVICE_MODEL_SCALE) {
    if (device.type === "network.cabinet") {
      const attrs = device.attributes || {};
      const role = this._cabinetRole(device);
      if (role === "ups_power" || role === "ups_battery") {
        const baseDimensions = role === "ups_battery" ? CABINET_DIMENSIONS.battery : CABINET_DIMENSIONS.ups;
        const dimensions = this._cabinetVisualDimensions(baseDimensions, modelScaleMultiplier, { floorEquipment: true });
        return Number(attrs.floor_elevation_m || 0) + dimensions.height + 0.28;
      }
      const rackUnits = Number(attrs.rack_units || this._rackUnitsFromLabel(device.label) || 12);
      const baseDimensions = CABINET_DIMENSIONS[rackUnits] || CABINET_DIMENSIONS[12];
      const dimensions = this._cabinetVisualDimensions(baseDimensions, modelScaleMultiplier, { floorEquipment: attrs.mount !== "wall" });
      const floorElevation = Number(attrs.floor_elevation_m || 0);
      if (attrs.mount === "wall" && attrs.top_edge_height_m) return floorElevation + Number(attrs.top_edge_height_m) + 0.28;
      return floorElevation + dimensions.height + 0.28;
    }
    return this.installHeightFor(device) + 0.36;
  }

  installHeightFor(device) {
    const attrs = device.attributes || {};
    const floorElevation = Number(attrs.floor_elevation_m || 0);
    if (Number.isFinite(Number(attrs.install_height_m))) return floorElevation + Number(attrs.install_height_m);
    const type = device.type || "";
    if (type === "network.ap") return floorElevation + (attrs.zone === "office" ? 3.2 : 6.0);
    if (type === "security.camera.fisheye") return floorElevation + 5.0;
    if (type === "security.camera.dome") return floorElevation + 3.0;
    if (type === "security.camera.rear") return floorElevation + 2.8;
    if (type.startsWith("security.camera")) return floorElevation + 3.5;
    return floorElevation + 0.4;
  }

  _visualScale(value) {
    const numeric = Number(value);
    return Number.isFinite(numeric) ? Math.max(MIN_DEVICE_MODEL_SCALE, Math.min(numeric, MAX_DEVICE_MODEL_SCALE)) : DEFAULT_DEVICE_MODEL_SCALE;
  }

  _rackUnitsFromLabel(label = "") {
    const match = String(label).match(/(\d{1,2})U/i);
    return match ? Number(match[1]) : null;
  }

  _cabinetRole(device) {
    const attrs = device.attributes || {};
    const role = String(attrs.cabinet_role || "");
    if (role === "ups_power" || role === "ups_battery") return role;
    const label = String(device.label || "").replace(/\s+/g, "").toUpperCase();
    if (label.includes("UPS") && label.includes("电池")) return "ups_battery";
    if (label.includes("UPS")) return "ups_power";
    return "";
  }

  _cabinetVisualDimensions(baseDimensions, visualScale = DEFAULT_DEVICE_MODEL_SCALE, options = {}) {
    const cabinetScale = options.floorEquipment
      ? FLOOR_CABINET_VISUAL_SCALE
      : CABINET_VISUAL_SCALE * this._visualScale(visualScale) * CABINET_VISUAL_SIZE_BOOST;
    return {
      width: baseDimensions.width * cabinetScale,
      depth: baseDimensions.depth * cabinetScale,
      height: baseDimensions.height * cabinetScale,
    };
  }

  _addMaintenanceFootprint(group, device, dimensions, color = COLORS.maintenance) {
    const attrs = device.attributes || {};
    const clearance = Math.max(
      DEFAULT_MAINTENANCE_CLEARANCE_M,
      Number(attrs.maintenance_clearance_m || 0),
      Number(attrs.service_channel_to_core_m || 0),
      Number(attrs.service_channel_to_ups_m || 0),
    );
    const floorElevation = Number(attrs.floor_elevation_m || 0);
    const footprint = new THREE.Mesh(
      new THREE.BoxGeometry(dimensions.width + clearance * 2, 0.018, dimensions.depth + clearance * 2),
      material(color, { transparent: true, opacity: 0.18, roughness: 0.8 }),
    );
    footprint.position.y = floorElevation + 0.012;
    group.add(footprint);
  }

  _floorCabinetY(device, height) {
    return Number(device.attributes?.floor_elevation_m || 0) + height / 2;
  }

  _makeCoverage(device, mapper, modelScale = DEFAULT_DEVICE_MODEL_SCALE) {
    const type = device.type || "";
    const pos2d = device.geometry?.position;
    if (!pos2d) return null;
    if (device.coverage?.disabled || device.attributes?.coverage_disabled) return null;

    if (type === "network.ap") {
      return this._makeProjectedDomeCoverage(device, mapper, pos2d, device.coverage?.radius_m ?? 14, 0x22d3ee, PROJECTED_COVERAGE_OPACITY.ap);
    }

    if (type === "security.camera.dome" && Number(device.coverage?.length_m || 0) > 0) {
      return this._makeProjectedSectorCoverage(
        device,
        mapper,
        pos2d,
        device.coverage.length_m,
        device.coverage?.angle_deg ?? 60,
        device.orientation?.angle_deg ?? 0,
        COLORS.dome,
        PROJECTED_COVERAGE_OPACITY.dome,
      );
    }

    if (type === "security.camera.dome" && Number(device.coverage?.radius_m || 0) > 0) {
      return this._makeProjectedDomeCoverage(
        device,
        mapper,
        pos2d,
        device.coverage.radius_m,
        COLORS.dome,
        PROJECTED_COVERAGE_OPACITY.dome,
      );
    }

    if (type === "security.camera.fisheye") {
      return this._makeProjectedDomeCoverage(
        device,
        mapper,
        pos2d,
        device.coverage?.radius_m ?? 10,
        COLORS.fisheye,
        PROJECTED_COVERAGE_OPACITY.fisheye,
      );
    }

    if (type.startsWith("security.camera")) {
      if (this._isDownlightCoverage(device)) {
        return this._makeProjectedDomeCoverage(
          device,
          mapper,
          pos2d,
          device.coverage?.radius_m ?? 3,
          COLORS.bullet,
          Math.max(0.20, PROJECTED_COVERAGE_OPACITY.bullet * 0.88),
        );
      }
      return this._makeProjectedSectorCoverage(
        device,
        mapper,
        pos2d,
        device.coverage?.length_m ?? 20,
        device.coverage?.angle_deg ?? 60,
        device.orientation?.angle_deg ?? 0,
        COLORS.bullet,
        PROJECTED_COVERAGE_OPACITY.bullet,
      );
    }

    return null;
  }

  _isDownlightCoverage(device) {
    const attrs = device.attributes || {};
    const coverage = device.coverage || {};
    const style = attrs.coverage_render_style || coverage.render_style || "";
    return style === "projected_downlight_cone" || style === "projected_volume_cone";
  }

  _makeProjectedSectorCoverage(device, mapper, pos2d, length, angleDeg, directionDeg, color, opacity) {
    const attrs = device.attributes || {};
    const floorElevation = Number(attrs.floor_elevation_m || 0);
    const installY = Math.max(this.installHeightFor(device), floorElevation + 0.35);
    const coverageAngleDeg = Math.max(5, Math.min(Number(angleDeg || 60), 170));
    const drawLength = Math.max(0.5, Number(length || 15));
    const halfAngle = THREE.MathUtils.degToRad(coverageAngleDeg / 2);
    const segments = Math.max(16, Math.ceil(coverageAngleDeg / 3));

    const shape = new THREE.Shape();
    shape.moveTo(0, 0);
    for (let index = 0; index <= segments; index += 1) {
      const t = index / segments;
      const angle = -halfAngle + t * halfAngle * 2;
      shape.lineTo(Math.sin(angle) * drawLength, Math.cos(angle) * drawLength);
    }
    shape.lineTo(0, 0);

    const group = new THREE.Group();
    group.userData = { selectable: true, entity: device, kind: "coverage" };
    group.position.copy(mapper.toVector3(pos2d, installY));
    group.rotation.y = yawFromCadAngle(directionDeg);

    const sectorMaterial = new THREE.MeshBasicMaterial({
      color,
      transparent: true,
      opacity,
      side: THREE.DoubleSide,
      depthWrite: false,
    });
    sectorMaterial.userData.baseOpacity = opacity;
    const sector = new THREE.Mesh(new THREE.ShapeGeometry(shape), sectorMaterial);
    sector.rotation.x = -Math.PI / 2;
    sector.userData = { selectable: true, entity: device, kind: "coverage", coveragePart: "projected_sector_plane" };
    group.add(sector);

    const emitter = new THREE.Mesh(
      new THREE.SphereGeometry(0.10, 12, 8),
      new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.72, depthWrite: false }),
    );
    emitter.userData = { selectable: true, entity: device, kind: "coverage", coveragePart: "emitter" };
    group.add(emitter);

    return group;
  }

  _makeProjectedRoundBeamCoverage(device, mapper, pos2d, length, angleDeg, directionDeg, color, opacity) {
    const attrs = device.attributes || {};
    const floorElevation = Number(attrs.floor_elevation_m || 0);
    const installY = Math.max(this.installHeightFor(device), floorElevation + 0.5);
    const coverageAngleDeg = Math.max(5, Math.min(Number(angleDeg || 60), 170));
    const drawLength = Math.max(0.5, Number(length || 20));
    const beamRadius = Math.max(0.25, Math.tan(THREE.MathUtils.degToRad(coverageAngleDeg / 2)) * drawLength);
    const group = new THREE.Group();
    group.userData = { selectable: true, entity: device, kind: "coverage" };
    group.position.copy(mapper.toVector3(pos2d, installY));
    group.rotation.y = yawFromCadAngle(directionDeg);

    const beamMaterial = new THREE.MeshBasicMaterial({
      color,
      transparent: true,
      opacity,
      side: THREE.DoubleSide,
      depthWrite: false,
    });
    beamMaterial.userData.baseOpacity = opacity;
    const beam = new THREE.Mesh(
      new THREE.CylinderGeometry(beamRadius, 0.08, drawLength, 48, 1, true),
      beamMaterial,
    );
    beam.rotation.x = -Math.PI / 2;
    beam.position.z = -drawLength / 2;
    beam.userData = { selectable: true, entity: device, kind: "coverage", coveragePart: "projected_round_beam" };
    group.add(beam);

    const emitter = new THREE.Mesh(
      new THREE.SphereGeometry(0.10, 12, 8),
      new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.72, depthWrite: false }),
    );
    emitter.userData = { selectable: true, entity: device, kind: "coverage", coveragePart: "emitter" };
    group.add(emitter);

    return group;
  }

  _makeProjectedDomeCoverage(device, mapper, pos2d, radius, color, opacity) {
    const attrs = device.attributes || {};
    const floorElevation = Number(attrs.floor_elevation_m || 0);
    const groundY = floorElevation + 0.08;
    const installY = Math.max(this.installHeightFor(device), groundY + 0.35);
    const height = installY - groundY;
    const group = new THREE.Group();
    group.userData = { selectable: true, entity: device, kind: "coverage" };
    const beamOpacity = Math.max(0.22, opacity);

    const beam = new THREE.Mesh(
      new THREE.CylinderGeometry(0.08, radius, height, 56, 1, true),
      new THREE.MeshBasicMaterial({
        color,
        transparent: true,
        opacity: beamOpacity,
        side: THREE.DoubleSide,
        depthWrite: false,
      }),
    );
    beam.material.userData.baseOpacity = beamOpacity;
    beam.position.copy(mapper.toVector3(pos2d, groundY + height / 2));
    beam.userData = { selectable: true, entity: device, kind: "coverage", coveragePart: "downlight_beam" };
    group.add(beam);

    const emitter = new THREE.Mesh(
      new THREE.SphereGeometry(Math.max(0.08, Math.min(radius * 0.010, 0.18)), 16, 10),
      new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.72, depthWrite: false }),
    );
    emitter.position.copy(mapper.toVector3(pos2d, installY));
    emitter.userData = { selectable: true, entity: device, kind: "coverage", coveragePart: "emitter" };
    group.add(emitter);

    if (device.type === "network.ap") {
      this._addApWifiRipples(group, device, mapper, pos2d, radius, color, groundY);
    }

    return group;
  }

  _addApWifiRipples(group, device, mapper, pos2d, radius, color, groundY) {
    const ringGeometry = new THREE.RingGeometry(0.965, 1, 96);
    for (let index = 0; index < AP_WIFI_RIPPLE_COUNT; index += 1) {
      const material = new THREE.MeshBasicMaterial({
        color,
        transparent: true,
        opacity: AP_WIFI_RIPPLE_OPACITY,
        side: THREE.DoubleSide,
        depthWrite: false,
      });
      material.userData.baseOpacity = AP_WIFI_RIPPLE_OPACITY;
      const ripple = new THREE.Mesh(ringGeometry, material);
      ripple.rotation.x = -Math.PI / 2;
      ripple.position.copy(mapper.toVector3(pos2d, groundY + 0.055 + index * 0.006));
      ripple.userData = {
        entity: device,
        kind: "coverage",
        coveragePart: "wifi_ripple",
        animation: "ap_wifi_ripple",
        radius,
        phase: index / AP_WIFI_RIPPLE_COUNT,
        baseOpacity: AP_WIFI_RIPPLE_OPACITY,
        speed: AP_WIFI_RIPPLE_SPEED,
      };
      group.add(ripple);
    }
  }
}

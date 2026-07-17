import * as THREE from "three";

const AREA_COLORS = {
  "area.parking": 0x22d3ee,
  "area.office": 0xb79cff,
  "area.office.mezzanine": 0xf4b43a,
  "area.office.room": 0x69d2e7,
  "area.office.open_workstations": 0x8fe1c1,
  "area.office.utility": 0xffcf6a,
  "area.office.stair": 0xf0df9b,
  "area.warehouse": 0xf4b43a,
  "area.warehouse.shell": 0x8fa09a,
  "area.lift_platform": 0xf4b43a,
  "area.parking_yard": 0x3e5f67,
  "area.dock_platform": 0x7f8f88,
  "room.control": 0x7ddc83,
};

function basic(color, opacity = 1) {
  return new THREE.MeshBasicMaterial({
    color,
    transparent: opacity < 1,
    opacity,
    side: THREE.DoubleSide,
    depthWrite: opacity >= 0.95,
  });
}

function standard(color, options = {}) {
  const opacity = options.opacity ?? 1;
  return new THREE.MeshStandardMaterial({
    color,
    roughness: options.roughness ?? 0.82,
    metalness: options.metalness ?? 0.02,
    transparent: opacity < 1,
    opacity,
    side: THREE.DoubleSide,
    depthWrite: opacity >= 0.95,
  });
}

export class AreaRenderer {
  renderShell(mapper) {
    const group = new THREE.Group();
    const ground = new THREE.Mesh(
      new THREE.PlaneGeometry(mapper.width * 1.14, mapper.depth * 1.14),
      standard(0x101410, { roughness: 0.92 }),
    );
    ground.rotation.x = -Math.PI / 2;
    ground.position.y = -0.012;
    group.add(ground);

    const lowerGrid = new THREE.GridHelper(Math.max(mapper.width, mapper.depth) * 1.14, 80, 0x1e261f, 0x171c18);
    lowerGrid.position.y = 0.002;
    group.add(lowerGrid);

    const floorHeight = mapper.floorHeight || 0;
    if (floorHeight > 0.05) {
      const slab = new THREE.Mesh(
        new THREE.BoxGeometry(mapper.width * 1.02, floorHeight, mapper.depth * 1.02),
        standard(0x171c17, { roughness: 0.9 }),
      );
      slab.position.y = floorHeight / 2;
      group.add(slab);

      const dockEdge = new THREE.Mesh(
        new THREE.BoxGeometry(mapper.width * 1.02, floorHeight * 0.96, 0.22),
        standard(0x303730, { roughness: 0.88 }),
      );
      dockEdge.position.set(0, floorHeight / 2, mapper.depth * 0.51);
      group.add(dockEdge);
    }

    const floor = new THREE.Mesh(
      new THREE.PlaneGeometry(mapper.width * 1.02, mapper.depth * 1.02),
      standard(0x151815, { roughness: 0.9 }),
    );
    floor.rotation.x = -Math.PI / 2;
    floor.position.y = floorHeight + 0.003;
    group.add(floor);

    const floorGrid = new THREE.GridHelper(Math.max(mapper.width, mapper.depth) * 1.02, 80, 0x334033, 0x242b24);
    floorGrid.position.y = floorHeight + 0.01;
    group.add(floorGrid);
    return group;
  }

  renderAreas(areas, mapper) {
    const group = new THREE.Group();
    areas.forEach((area) => {
      const points = area.geometry?.points || [];
      if (points.length < 3) return;
      if (area.type === "area.warehouse.shell") {
        group.add(this._renderWarehouseShell(area, mapper));
        return;
      }
      if (area.type === "area.lift_platform") {
        group.add(this._renderLiftPlatform(area, mapper));
        return;
      }
      if (area.attributes?.absolute_elevation || area.type === "area.parking_yard" || area.type === "area.dock_platform") {
        group.add(this._renderAbsoluteArea(area, mapper));
        return;
      }
      group.add(this._renderPlanArea(area, mapper));
    });
    return group;
  }

  _renderWarehouseShell(area, mapper) {
    const group = new THREE.Group();
    group.userData = { selectable: true, entity: area, kind: "area" };
    const points = area.geometry?.points || [];
    if (area.attributes?.inferred_from === "dock_layout_subject") {
      const floorHeight = mapper.floorHeight || 0;
      const wallHeight = Number(area.attributes?.height_m || mapper.warehouseHeight || 10.5);
      group.add(this._wallRing(points, mapper, floorHeight, wallHeight, 0x8fa09a, 0.34, 0.28));
      group.add(this._outline(points, mapper, floorHeight + wallHeight + 0.02, 0xd8e3df, 0.68));
      return group;
    }
    const floorHeight = mapper.floorHeight || 0;
    const wallHeight = Number(area.attributes?.height_m || mapper.warehouseHeight || 10.5);
    const peakHeight = Number(area.attributes?.roof_peak_height_m || mapper.roofPeakHeight || wallHeight);
    group.add(this._wallRing(points, mapper, floorHeight, wallHeight, 0x8fa09a, 0.42, 0.34));
    group.add(this._outline(points, mapper, floorHeight + wallHeight + 0.02, 0xd8e3df, 0.72));

    const roof = new THREE.Mesh(
      this._shapeGeometry(points, mapper),
      standard(0x66726d, { roughness: 0.86, opacity: 0.13 }),
    );
    roof.position.y = floorHeight + peakHeight;
    roof.userData = { selectable: true, entity: area, kind: "area" };
    group.add(roof);
    return group;
  }

  _renderPlanArea(area, mapper) {
    const group = new THREE.Group();
    group.userData = { selectable: true, entity: area, kind: "area" };
    const points = area.geometry?.points || [];
    const color = this._areaColor(area);
    const floorHeight = mapper.floorHeight || 0;
    const fallbackDeckHeight = area.type === "area.office.mezzanine" ? Number(area.attributes?.deck_height_m || 0) : 0;
    const floorElevation = Number(area.attributes?.floor_elevation_m ?? fallbackDeckHeight);
    const roomHeight = Number(area.attributes?.room_height_m || area.attributes?.height_m || 3.4);
    const y = floorHeight + floorElevation + 0.04;
    const opacity = Number(area.attributes?.opacity ?? (area.type === "area.office.mezzanine" ? 0.24 : 0.16));
    const renderSolid = area.attributes?.render_solid !== false;
    const renderScopeOnly = area.attributes?.render_as_scope === true || !renderSolid;
    const isStackedGatehouseMezzanine =
      area.type === "area.office.mezzanine" &&
      String(area.attributes?.stacking_source || "").startsWith("same_gatehouse_footprint");
    const isGatehouseStackedFloor =
      (area.type === "area.office" || area.type === "area.office.mezzanine") &&
      area.attributes?.tower &&
      area.attributes?.footprint_source === "cad_gatehouse_main_plan_footprint";

    if (renderSolid && !renderScopeOnly && !isStackedGatehouseMezzanine && !isGatehouseStackedFloor) {
      const mesh = new THREE.Mesh(this._shapeGeometry(points, mapper), basic(color, opacity));
      mesh.position.y = y;
      mesh.userData = { selectable: true, entity: area, kind: "area" };
      group.add(mesh);
    }
    group.add(this._outline(points, mapper, y + 0.012, color, renderScopeOnly ? 0.42 : 0.9));

    const renderOfficeWalls = (area.type === "area.office" || area.type === "area.office.mezzanine") && !renderScopeOnly;
    if (renderOfficeWalls) {
      if (!isStackedGatehouseMezzanine && !isGatehouseStackedFloor) {
        const slab = new THREE.Mesh(this._shapeGeometry(points, mapper), standard(0x2c3434, { roughness: 0.78, opacity: 0.35 }));
        slab.position.y = floorHeight + floorElevation;
        group.add(slab);
      }
      group.add(this._wallRing(points, mapper, floorHeight + floorElevation, roomHeight, color, 0.16, 0.18));
      group.add(this._outline(points, mapper, floorHeight + floorElevation + roomHeight + 0.02, color, 0.48));
    }

    if (floorElevation > 0.1) {
      group.add(this._outline(points, mapper, floorHeight + 0.06, 0xb79cff, 0.38));
      group.add(this._verticalCorners(points, mapper, floorHeight, y, color));
    }
    return group;
  }

  _areaColor(area) {
    const raw = area.attributes?.render_color;
    if (typeof raw === "number" && Number.isFinite(raw)) return raw;
    if (typeof raw === "string") {
      const normalized = raw.trim().replace(/^#/, "0x");
      const parsed = Number(normalized);
      if (Number.isFinite(parsed)) return parsed;
    }
    return AREA_COLORS[area.type] || 0x7ddc83;
  }

  _renderAbsoluteArea(area, mapper) {
    const group = new THREE.Group();
    group.userData = { selectable: true, entity: area, kind: "area" };
    const points = area.geometry?.points || [];
    const color = AREA_COLORS[area.type] || 0x7ddc83;
    if (area.type === "area.parking_yard" || area.attributes?.render_solid === false) {
      const elevation = Number(area.attributes?.floor_elevation_m || 0);
      group.add(this._outline(points, mapper, elevation + 0.025, color, 0.16));
      return group;
    }
    if (this._isInferredDockPlatform(area)) {
      const elevation = Number(area.attributes?.floor_elevation_m || 0);
      group.add(this._outline(points, mapper, elevation + 0.055, color, 0.18));
      return group;
    }
    const elevation = Number(area.attributes?.floor_elevation_m || 0);
    const opacity = area.type === "area.dock_platform" ? 0.08 : 0.10;
    const y = elevation + 0.035;

    const mesh = new THREE.Mesh(this._shapeGeometry(points, mapper), basic(color, opacity));
    mesh.position.y = y;
    mesh.userData = { selectable: true, entity: area, kind: "area" };
    group.add(mesh);
    group.add(this._outline(points, mapper, y + 0.012, color, area.type === "area.dock_platform" ? 0.42 : 0.46));

    if (area.type === "area.dock_platform") {
      const deck = new THREE.Mesh(this._shapeGeometry(points, mapper), standard(0x262c27, { roughness: 0.82, opacity: 0.12 }));
      deck.position.y = elevation + 0.02;
      group.add(deck);
    }
    return group;
  }

  _isInferredDockPlatform(area) {
    if (area.type !== "area.dock_platform") return false;
    const source = String(area.attributes?.source || "");
    return source.includes("推断") || source.includes("自动生成");
  }

  _renderLiftPlatform(area, mapper) {
    const group = new THREE.Group();
    group.userData = { selectable: true, entity: area, kind: "area" };
    const points = area.geometry?.points || [];
    const height = Number(area.attributes?.height_m || mapper.floorHeight || 1.2);

    const deck = new THREE.Mesh(this._shapeGeometry(points, mapper), standard(0x303435, { roughness: 0.56, metalness: 0.28 }));
    deck.position.y = height + 0.03;
    deck.userData = { selectable: true, entity: area, kind: "area" };
    group.add(deck);

    group.add(this._outline(points, mapper, height + 0.06, 0xf4b43a, 1));
    group.add(this._edgeWalls(points, mapper, height, 0x141616));
    group.add(this._hazardStripes(points, mapper, height + 0.085));
    return group;
  }

  renderStructures(structures, mapper) {
    const group = new THREE.Group();
    const wallMat = new THREE.LineBasicMaterial({ color: 0x6688aa, opacity: 0.7, transparent: true });
    const outlineMat = new THREE.LineBasicMaterial({ color: 0xaabbcc, opacity: 0.9, transparent: true });
    const platformMat = new THREE.LineBasicMaterial({ color: 0xf4b43a, opacity: 0.7, transparent: true });
    const columnMat = new THREE.MeshBasicMaterial({ color: 0x7799bb, transparent: true, opacity: 0.82 });
    const wallTopMat = new THREE.LineBasicMaterial({ color: 0xb8c7c2, opacity: 0.48, transparent: true });

    structures.forEach((structure) => {
      const geometry = structure.geometry || {};
      const attrs = structure.attributes || {};
      if (this._skipReferenceStructure(structure)) return;
      const floorElevation = Number(attrs.floor_elevation_m || 0);
      if (this._isRackStructure(structure) && geometry.type === "Point" && geometry.position) {
        const rack = this._rackUnit(structure, mapper, floorElevation);
        if (rack) group.add(rack);
        return;
      }
      if (geometry.type === "Circle" && structure.type === "building.column") {
        const height = Number(attrs.room_height_m || mapper.warehouseHeight || 10.5);
        const center = mapper.toVector3(geometry.center, floorElevation + height / 2);
        const radius = Math.max((geometry.radius || 300) * mapper.scale, 0.18);
        const column = new THREE.Mesh(new THREE.CylinderGeometry(radius, radius, height, 16), columnMat);
        column.position.copy(center);
        group.add(column);
        return;
      }

      const points = geometry.points || [];
      if (points.length < 2) return;
      if (this._isRackStructure(structure) && geometry.closed && points.length > 2) {
        const rackFootprint = this._rackFootprint(structure, points, mapper, floorElevation);
        if (rackFootprint) group.add(rackFootprint);
        return;
      }
      const mat = structure.type === "building.outline"
        ? outlineMat
        : structure.type === "building.platform"
          ? platformMat
          : wallMat;
      const baseY = (mapper.floorHeight || 0) + floorElevation;
      const vectors = mapper.pointsToVectors(points, floorElevation + 0.06);
      if (geometry.closed && vectors.length > 2) vectors.push(vectors[0].clone());
      const lineGeometry = new THREE.BufferGeometry().setFromPoints(vectors);
      const line = new THREE.Line(lineGeometry, mat);
      line.userData = { selectable: true, entity: structure, kind: "structure" };
      group.add(line);

      const canExtrudeFallbackWall = attrs.source_kind !== "fallback_structure_layer" || Boolean(geometry.closed);
      if ((structure.type === "building.wall" && canExtrudeFallbackWall) || structure.type === "building.outline") {
        const height = this._structureWallHeight(structure, mapper);
        const thickness = structure.layer?.includes("防火") ? 0.24 : 0.16;
        const wallGroup = this._wallSegments(points, mapper, baseY, height, structure.type === "building.outline" ? 0xaab8b3 : 0x6f807b, 0.36, thickness, Boolean(geometry.closed));
        wallGroup.userData = { selectable: true, entity: structure, kind: "structure" };
        group.add(wallGroup);
        const topVectors = mapper.pointsToVectors(points, floorElevation + height + 0.04);
        if (geometry.closed && topVectors.length > 2) topVectors.push(topVectors[0].clone());
        group.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(topVectors), wallTopMat));
      }
    });

    return group;
  }

  _isRackStructure(structure) {
    const type = String(structure.type || "");
    const attrs = structure.attributes || {};
    return type.includes("rack") || String(attrs.render_role || "").includes("rack") || String(attrs.render_role || "").includes("pallet");
  }

  _rackUnit(structure, mapper, floorElevation) {
    const attrs = structure.attributes || {};
    const role = String(attrs.render_role || "");
    const height = Number(attrs.height_m || (role.includes("pallet") ? 0.22 : 2.2));
    const width = Math.max(Number(attrs.width_m || 1.2), 0.3);
    const depth = Math.max(Number(attrs.depth_m || 1.0), 0.3);
    const baseY = (mapper.floorHeight || 0) + floorElevation;
    const center = mapper.toVector3(structure.geometry.position, floorElevation + height / 2);
    const color = role.includes("pallet") ? 0x26c6b8 : 0x58d68d;
    const rack = new THREE.Mesh(
      new THREE.BoxGeometry(width, height, depth),
      standard(color, { roughness: 0.72, metalness: role.includes("pallet") ? 0.02 : 0.12, opacity: 0.82 }),
    );
    rack.position.set(center.x, baseY + height / 2, center.z);
    rack.rotation.y = -THREE.MathUtils.degToRad(Number(attrs.rotation_deg || 0));
    rack.userData = { selectable: true, entity: structure, kind: "structure" };

    const group = new THREE.Group();
    group.add(rack);
    if (!role.includes("pallet")) {
      const shelf = new THREE.LineSegments(
        new THREE.EdgesGeometry(new THREE.BoxGeometry(width * 1.02, height * 1.02, depth * 1.02)),
        new THREE.LineBasicMaterial({ color: 0xbff8ec, opacity: 0.45, transparent: true }),
      );
      shelf.position.copy(rack.position);
      shelf.rotation.copy(rack.rotation);
      group.add(shelf);
    }
    return group;
  }

  _rackFootprint(structure, points, mapper, floorElevation) {
    const baseY = (mapper.floorHeight || 0) + floorElevation;
    const deck = new THREE.Mesh(
      this._shapeGeometry(points, mapper),
      standard(0x2dd4bf, { roughness: 0.78, opacity: 0.18 }),
    );
    deck.position.y = baseY + 0.035;
    deck.userData = { selectable: true, entity: structure, kind: "structure" };
    const group = new THREE.Group();
    group.add(deck);
    group.add(this._outline(points, mapper, baseY + 0.08, 0x63f3dc, 0.62));
    return group;
  }

  _skipReferenceStructure(structure) {
    const attrs = structure.attributes || {};
    const matchedLayer = String(attrs.matched_layer || structure.layer || "");
    if (structure.type === "building.road" && attrs.source_kind === "fallback_structure_layer") return true;
    if (matchedLayer === "A-ROAD" || matchedLayer === "A-ROAD-CENTER" || matchedLayer === "A-ROAD-RED") return true;
    return false;
  }

  _structureWallHeight(structure, mapper) {
    if (Number(structure.attributes?.room_height_m) > 0) return Number(structure.attributes.room_height_m);
    if (structure.layer?.includes("防火") || structure.layer?.includes("砼墙")) return mapper.warehouseHeight || 10.5;
    return Math.min(mapper.warehouseHeight || 10.5, 4.2);
  }

  _shapeGeometry(points, mapper) {
    const shape = new THREE.Shape(points.map((point) => {
      const mapped = mapper.toXZ(point);
      return new THREE.Vector2(mapped.x, mapped.z);
    }));
    const geometry = new THREE.ShapeGeometry(shape);
    geometry.rotateX(-Math.PI / 2);
    return geometry;
  }

  _outline(points, mapper, y, color, opacity = 1) {
    const vectors = points.map((point) => {
      const mapped = mapper.toXZ(point);
      return new THREE.Vector3(mapped.x, y, mapped.z);
    });
    vectors.push(vectors[0].clone());
    return new THREE.Line(
      new THREE.BufferGeometry().setFromPoints(vectors),
      new THREE.LineBasicMaterial({ color, transparent: opacity < 1, opacity }),
    );
  }

  _verticalCorners(points, mapper, y1, y2, color) {
    const group = new THREE.Group();
    points.forEach((point) => {
      const mapped = mapper.toXZ(point);
      const geometry = new THREE.BufferGeometry().setFromPoints([
        new THREE.Vector3(mapped.x, y1, mapped.z),
        new THREE.Vector3(mapped.x, y2, mapped.z),
      ]);
      group.add(new THREE.Line(geometry, new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.55 })));
    });
    return group;
  }

  _wallRing(points, mapper, baseY, height, color, opacity, thickness) {
    return this._wallSegments(points, mapper, baseY, height, color, opacity, thickness, true);
  }

  _wallSegments(points, mapper, baseY, height, color, opacity, thickness, closed = false) {
    const group = new THREE.Group();
    const mapped = points.map((point) => mapper.toXZ(point));
    const pairCount = closed ? mapped.length : mapped.length - 1;
    for (let index = 0; index < pairCount; index += 1) {
      const point = mapped[index];
      const next = mapped[(index + 1) % mapped.length];
      const dx = next.x - point.x;
      const dz = next.z - point.z;
      const length = Math.hypot(dx, dz);
      if (length < 0.35) continue;
      const wall = new THREE.Mesh(
        new THREE.BoxGeometry(length, Math.max(height, 0.1), thickness),
        standard(color, { roughness: 0.78, opacity }),
      );
      wall.position.set((point.x + next.x) / 2, baseY + height / 2, (point.z + next.z) / 2);
      wall.rotation.y = -Math.atan2(dz, dx);
      group.add(wall);
    }
    return group;
  }

  _edgeWalls(points, mapper, height, color) {
    const group = new THREE.Group();
    const mapped = points.map((point) => mapper.toXZ(point));
    mapped.forEach((point, index) => {
      const next = mapped[(index + 1) % mapped.length];
      const dx = next.x - point.x;
      const dz = next.z - point.z;
      const length = Math.hypot(dx, dz);
      if (length <= 0) return;
      const wall = new THREE.Mesh(
        new THREE.BoxGeometry(length, Math.max(height, 0.1), 0.08),
        standard(color, { roughness: 0.72 }),
      );
      wall.position.set((point.x + next.x) / 2, height / 2, (point.z + next.z) / 2);
      wall.rotation.y = -Math.atan2(dz, dx);
      group.add(wall);
    });
    return group;
  }

  _hazardStripes(points, mapper, y) {
    const group = new THREE.Group();
    const mapped = points.map((point) => mapper.toXZ(point));
    mapped.forEach((point, index) => {
      const next = mapped[(index + 1) % mapped.length];
      const dx = next.x - point.x;
      const dz = next.z - point.z;
      const length = Math.hypot(dx, dz);
      if (length <= 0) return;
      const stripeCount = Math.max(2, Math.floor(length / 0.55));
      for (let i = 0; i < stripeCount; i += 1) {
        const t = (i + 0.5) / stripeCount;
        const stripe = new THREE.Mesh(
          new THREE.BoxGeometry(Math.min(0.34, length / stripeCount), 0.018, 0.08),
          basic(i % 2 === 0 ? 0xf4b43a : 0x0c0d0c, 1),
        );
        stripe.position.set(point.x + dx * t, y, point.z + dz * t);
        stripe.rotation.y = -Math.atan2(dz, dx) + Math.PI / 4;
        group.add(stripe);
      }
    });
    return group;
  }
}

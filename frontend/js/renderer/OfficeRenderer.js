import * as THREE from "three";

const MEETING_TABLE_OVERLAP_PAD_MM = 650;
const MEETING_TABLE_OVERLAP_SEAT_TYPES = new Set(["office.training_seat", "office.workstation_seat"]);

function material(color, options = {}) {
  const opacity = options.opacity ?? 1;
  return new THREE.MeshStandardMaterial({
    color,
    roughness: options.roughness ?? 0.62,
    metalness: options.metalness ?? 0.03,
    transparent: opacity < 1,
    opacity,
    side: THREE.DoubleSide,
    depthWrite: opacity >= 0.95,
  });
}

export class OfficeRenderer {
  render(objects, mapper) {
    const group = new THREE.Group();
    this._filterMeetingTableSeatOverlaps(objects).forEach((item) => {
      if (item.type === "office.workstation") {
        group.add(this._workstation(item, mapper));
      } else if (item.type === "office.workstation_seat") {
        group.add(this._workstationSeat(item, mapper));
      } else if (item.type === "office.desk_row") {
        group.add(this._deskRow(item, mapper));
      } else if (item.type === "office.l_desk") {
        group.add(this._lDesk(item, mapper));
      } else if (item.type === "office.training_seat") {
        group.add(this._trainingSeat(item, mapper));
      } else if (item.type === "office.meeting_table") {
        group.add(this._meetingTable(item, mapper));
      } else if (item.type === "office.partition") {
        const partition = this._partition(item, mapper);
        if (partition) group.add(partition);
      } else if (item.type === "office.stair") {
        const stair = this._stair(item, mapper);
        if (stair) group.add(stair);
      } else if (item.type === "office.stairwell") {
        const stairwell = this._stairwell(item, mapper);
        if (stairwell) group.add(stairwell);
      } else if (item.type === "logistics.conveyor_belt") {
        group.add(this._conveyor(item, mapper));
      } else if (item.type === "logistics.dws_host") {
        group.add(this._dwsHost(item, mapper));
      }
    });
    return group;
  }

  _filterMeetingTableSeatOverlaps(objects) {
    const tables = objects.filter((item) => item.type === "office.meeting_table" && item.geometry?.position);
    if (!tables.length) return objects;
    return objects.filter((item) => {
      if (!MEETING_TABLE_OVERLAP_SEAT_TYPES.has(item.type) || !item.geometry?.position) return true;
      return !tables.some((table) => {
        if (!this._sameFloor(item, table)) return false;
        const radiusMm = Math.max(Number(table.attributes?.radius_m || 0.55) * 1000, 350);
        const dx = Number(item.geometry.position.x) - Number(table.geometry.position.x);
        const dy = Number(item.geometry.position.y) - Number(table.geometry.position.y);
        return Math.hypot(dx, dy) <= radiusMm + MEETING_TABLE_OVERLAP_PAD_MM;
      });
    });
  }

  _sameFloor(left, right) {
    const leftAttrs = left.attributes || {};
    const rightAttrs = right.attributes || {};
    const leftFloor = String(leftAttrs.floor_id || leftAttrs.floor_label || "");
    const rightFloor = String(rightAttrs.floor_id || rightAttrs.floor_label || "");
    if (leftFloor && rightFloor) return leftFloor === rightFloor;
    const leftElevation = Number(leftAttrs.floor_elevation_m || 0);
    const rightElevation = Number(rightAttrs.floor_elevation_m || 0);
    return Math.abs(leftElevation - rightElevation) < 0.2;
  }

  _workstation(item, mapper) {
    const floorElevation = Number(item.attributes?.floor_elevation_m || 0);
    const position = mapper.toVector3(item.geometry?.position, floorElevation);
    const group = new THREE.Group();
    group.position.copy(position);
    group.rotation.y = THREE.MathUtils.degToRad(-(item.orientation?.angle_deg || 0));
    group.userData = { selectable: true, entity: item, kind: "office" };

    const desk = new THREE.Mesh(
      new THREE.BoxGeometry(1.15, 0.06, 0.62),
      material(0x72c7d8, { roughness: 0.54 }),
    );
    desk.position.y = 0.72;
    group.add(desk);

    const modesty = new THREE.Mesh(
      new THREE.BoxGeometry(1.05, 0.42, 0.035),
      material(0x2d5f68, { roughness: 0.7 }),
    );
    modesty.position.set(0, 0.48, -0.28);
    group.add(modesty);

    [-0.46, 0.46].forEach((x) => {
      [-0.22, 0.22].forEach((z) => {
        const leg = new THREE.Mesh(
          new THREE.CylinderGeometry(0.018, 0.018, 0.68, 8),
          material(0x8aa1a8, { roughness: 0.42, metalness: 0.22 }),
        );
        leg.position.set(x, 0.34, z);
        group.add(leg);
      });
    });

    const chair = new THREE.Mesh(
      new THREE.BoxGeometry(0.42, 0.08, 0.42),
      material(0xb8d6df, { roughness: 0.58 }),
    );
    chair.position.set(0, 0.45, 0.62);
    group.add(chair);

    const chairBack = new THREE.Mesh(
      new THREE.BoxGeometry(0.42, 0.48, 0.06),
      material(0x6b8790, { roughness: 0.64 }),
    );
    chairBack.position.set(0, 0.72, 0.84);
    group.add(chairBack);

    return group;
  }

  _workstationSeat(item, mapper) {
    const floorElevation = Number(item.attributes?.floor_elevation_m || 0);
    const group = new THREE.Group();
    group.position.copy(mapper.toVector3(item.geometry?.position, floorElevation));
    this._orientSeat(group, item, mapper, floorElevation);
    group.userData = { selectable: true, entity: item, kind: "office" };

    const seat = new THREE.Mesh(
      new THREE.BoxGeometry(0.42, 0.09, 0.42),
      material(0xb8dce5, { roughness: 0.58 }),
    );
    seat.position.y = 0.44;
    group.add(seat);

    const back = new THREE.Mesh(
      new THREE.BoxGeometry(0.42, 0.46, 0.06),
      material(0x6e8d98, { roughness: 0.64 }),
    );
    back.position.set(0, 0.72, 0.23);
    group.add(back);

    const pedestal = new THREE.Mesh(
      new THREE.CylinderGeometry(0.035, 0.035, 0.42, 10),
      material(0x8aa1a8, { roughness: 0.42, metalness: 0.2 }),
    );
    pedestal.position.y = 0.22;
    group.add(pedestal);

    return group;
  }

  _orientSeat(group, item, mapper, floorElevation) {
    const target = item.attributes?.face_towards;
    if (target && Number.isFinite(Number(target.x)) && Number.isFinite(Number(target.y))) {
      const targetVector = mapper.toVector3({ x: Number(target.x), y: Number(target.y) }, floorElevation);
      const dx = targetVector.x - group.position.x;
      const dz = targetVector.z - group.position.z;
      if (Math.hypot(dx, dz) > 0.001) {
        group.rotation.y = Math.atan2(-dx, -dz);
        return;
      }
    }
    group.rotation.y = THREE.MathUtils.degToRad(-(item.orientation?.angle_deg || 0));
  }

  _deskRow(item, mapper) {
    const attrs = item.attributes || {};
    const floorElevation = Number(attrs.floor_elevation_m || 0);
    const length = Math.max(Number(attrs.length_m || 4.6), 1.2);
    const width = Math.max(Number(attrs.width_m || 0.8), 0.45);
    const modules = Math.max(Math.round(Number(attrs.modules || 4)), 1);
    const group = new THREE.Group();
    group.position.copy(mapper.toVector3(item.geometry?.position, floorElevation));
    group.rotation.y = THREE.MathUtils.degToRad(-(item.orientation?.angle_deg || 0));
    group.userData = { selectable: true, entity: item, kind: "office" };

    const desktop = new THREE.Mesh(
      new THREE.BoxGeometry(length, 0.07, width),
      material(0x82d7e8, { roughness: 0.54 }),
    );
    desktop.position.y = 0.72;
    group.add(desktop);

    const dividerMat = material(0x2d6670, { roughness: 0.7 });
    for (let i = 1; i < modules; i += 1) {
      const divider = new THREE.Mesh(new THREE.BoxGeometry(0.035, 0.08, width + 0.04), dividerMat);
      divider.position.set(-length / 2 + (length * i) / modules, 0.77, 0);
      group.add(divider);
    }

    [-0.48, 0.48].forEach((z) => {
      const modesty = new THREE.Mesh(
        new THREE.BoxGeometry(length * 0.96, 0.32, 0.035),
        material(0x2d6670, { roughness: 0.7, opacity: 0.9 }),
      );
      modesty.position.set(0, 0.49, z * width);
      group.add(modesty);
    });

    return group;
  }

  _lDesk(item, mapper) {
    const attrs = item.attributes || {};
    const floorElevation = Number(attrs.floor_elevation_m || 0);
    const mainLength = Math.max(Number(attrs.main_length_m || 1.85), 1.0);
    const mainWidth = Math.max(Number(attrs.main_width_m || 0.72), 0.45);
    const returnLength = Math.max(Number(attrs.return_length_m || 1.45), 0.8);
    const returnWidth = Math.max(Number(attrs.return_width_m || 0.72), 0.45);
    const returnSide = String(attrs.return_side || "right") === "left" ? -1 : 1;
    const returnEnd = String(attrs.return_end || "front") === "back" ? 1 : -1;
    const group = new THREE.Group();
    group.position.copy(mapper.toVector3(item.geometry?.position, floorElevation));
    group.rotation.y = THREE.MathUtils.degToRad(-(item.orientation?.angle_deg || 0));
    group.userData = { selectable: true, entity: item, kind: "office" };

    const deskMat = material(0x82d7e8, { roughness: 0.54 });
    const edgeMat = material(0x2d6670, { roughness: 0.7, opacity: 0.9 });

    const main = new THREE.Mesh(new THREE.BoxGeometry(mainWidth, 0.07, mainLength), deskMat);
    main.position.y = 0.72;
    group.add(main);

    const ret = new THREE.Mesh(new THREE.BoxGeometry(returnLength, 0.07, returnWidth), deskMat);
    ret.position.set(
      returnSide * (mainWidth / 2 + returnLength / 2 - 0.08),
      0.72,
      returnEnd * (mainLength / 2 - returnWidth / 2),
    );
    group.add(ret);

    const connector = new THREE.Mesh(
      new THREE.BoxGeometry(mainWidth + 0.16, 0.075, returnWidth),
      deskMat,
    );
    connector.position.set(0, 0.724, returnEnd * (mainLength / 2 - returnWidth / 2));
    group.add(connector);

    const mainPanel = new THREE.Mesh(new THREE.BoxGeometry(0.035, 0.32, mainLength * 0.9), edgeMat);
    mainPanel.position.set(-returnSide * mainWidth * 0.45, 0.49, 0);
    group.add(mainPanel);

    const returnPanel = new THREE.Mesh(new THREE.BoxGeometry(returnLength * 0.86, 0.32, 0.035), edgeMat);
    returnPanel.position.set(
      returnSide * (mainWidth / 2 + returnLength / 2 - 0.08),
      0.49,
      returnEnd * (mainLength / 2 - returnWidth * 0.9),
    );
    group.add(returnPanel);

    return group;
  }

  _trainingSeat(item, mapper) {
    if (item.attributes?.seat_only === true) {
      return this._workstationSeat(item, mapper);
    }
    const floorElevation = Number(item.attributes?.floor_elevation_m || 0);
    const group = new THREE.Group();
    group.position.copy(mapper.toVector3(item.geometry?.position, floorElevation));
    group.rotation.y = THREE.MathUtils.degToRad(-(item.orientation?.angle_deg || 0));
    group.userData = { selectable: true, entity: item, kind: "office" };

    const desk = new THREE.Mesh(
      new THREE.BoxGeometry(0.82, 0.055, 0.42),
      material(0x87d7e8, { roughness: 0.54 }),
    );
    desk.position.set(0, 0.72, -0.16);
    group.add(desk);

    const chair = new THREE.Mesh(
      new THREE.BoxGeometry(0.36, 0.08, 0.34),
      material(0xb9dce5, { roughness: 0.58 }),
    );
    chair.position.set(0, 0.44, 0.34);
    group.add(chair);

    const back = new THREE.Mesh(
      new THREE.BoxGeometry(0.36, 0.38, 0.055),
      material(0x6d8b96, { roughness: 0.64 }),
    );
    back.position.set(0, 0.66, 0.53);
    group.add(back);

    return group;
  }

  _meetingTable(item, mapper) {
    const floorElevation = Number(item.attributes?.floor_elevation_m || 0);
    const seats = Math.max(Number(item.attributes?.seats || 4), 2);
    const radius = Math.max(Number(item.attributes?.radius_m || 0.55), 0.35);
    const group = new THREE.Group();
    group.position.copy(mapper.toVector3(item.geometry?.position, floorElevation));
    group.rotation.y = THREE.MathUtils.degToRad(-(item.orientation?.angle_deg || 0));
    group.userData = { selectable: true, entity: item, kind: "office" };

    const table = new THREE.Mesh(
      new THREE.CylinderGeometry(radius, radius, 0.08, 32),
      material(0x86d6e5, { roughness: 0.56 }),
    );
    table.position.y = 0.72;
    group.add(table);

    for (let i = 0; i < seats; i += 1) {
      const angle = (Math.PI * 2 * i) / seats;
      const chairDistance = radius + 0.72;
      const chairGroup = new THREE.Group();
      chairGroup.position.set(
        Math.cos(angle) * chairDistance,
        0,
        Math.sin(angle) * chairDistance,
      );
      chairGroup.rotation.y = Math.PI / 2 - angle;

      const chair = new THREE.Mesh(
        new THREE.BoxGeometry(0.36, 0.08, 0.34),
        material(0xb9dce5, { roughness: 0.58 }),
      );
      chair.position.set(0, 0.44, 0);
      chairGroup.add(chair);

      const back = new THREE.Mesh(
        new THREE.BoxGeometry(0.36, 0.36, 0.055),
        material(0x6d8b96, { roughness: 0.64 }),
      );
      back.position.set(0, 0.66, 0.22);
      chairGroup.add(back);

      const pedestal = new THREE.Mesh(
        new THREE.CylinderGeometry(0.035, 0.035, 0.38, 8),
        material(0xbfd4db, { roughness: 0.66 }),
      );
      pedestal.position.y = 0.24;
      chairGroup.add(pedestal);

      group.add(chairGroup);
    }

    return group;
  }

  _partition(item, mapper) {
    const subtype = String(item.attributes?.subtype || "");
    const style = subtype === "glass_partition"
      ? { color: 0x7dd3fc, opacity: 0.38 }
      : subtype === "door_window"
        ? { color: 0xf4c76a, opacity: 0.56 }
        : { color: 0x9fb8c0, opacity: 0.68 };
    return this._segmentBox(item, mapper, {
      height: Number(item.attributes?.height_m || 2.4),
      width: Number(item.attributes?.width_m || 0.16),
      color: style.color,
      opacity: style.opacity,
      yLift: 0,
    });
  }

  _stair(item, mapper) {
    if (item.attributes?.subtype === "stair_opening") {
      return this._segmentBox(item, mapper, {
        height: 0.08,
        width: Number(item.attributes?.width_m || 0.08),
        color: 0xf4c76a,
        opacity: 0.46,
        yLift: 0.08,
      });
    }
    const base = this._segmentBox(item, mapper, {
      height: 0.2,
      width: 1.05,
      color: 0xe2c979,
      opacity: 0.86,
      yLift: 0.1,
    });
    if (!base) return null;
    const steps = 6;
    for (let i = 0; i < steps; i += 1) {
      const step = new THREE.Mesh(
        new THREE.BoxGeometry(0.9, 0.055, 0.18),
        material(0xf0df9b, { roughness: 0.7 }),
      );
      step.position.z = (i - (steps - 1) / 2) * 0.2;
      step.position.y = 0.15 + i * 0.035;
      base.add(step);
    }
    return base;
  }

  _stairwell(item, mapper) {
    const attrs = item.attributes || {};
    if (attrs.render_model === false) return null;
    const sourceKind = String(attrs.source_kind || "");
    if (attrs.tower || sourceKind.includes("cad_stair_lines_connected_floor_pair")) {
      return this._gatehouseStairwell(item, mapper);
    }
    const floorElevation = Number(attrs.floor_elevation_m || 0);
    const topElevation = Number(attrs.connects_to_elevation_m || floorElevation + 5.5);
    const height = Math.max(topElevation - floorElevation, 1.0);
    const length = Math.max(Number(attrs.length_m || 4.8), 1.8);
    const width = Math.max(Number(attrs.width_m || 1.6), 0.8);
    const steps = Math.max(Math.round(length / 0.38), 10);
    const group = new THREE.Group();
    group.position.copy(mapper.toVector3(item.geometry?.position, floorElevation));
    group.rotation.y = THREE.MathUtils.degToRad(-(item.orientation?.angle_deg || 0));
    group.userData = { selectable: true, entity: item, kind: "office" };

    for (let i = 0; i < steps; i += 1) {
      const progress = i / Math.max(steps - 1, 1);
      const step = new THREE.Mesh(
        new THREE.BoxGeometry(width, 0.08, length / steps * 0.92),
        material(0xf1d27a, { roughness: 0.66 }),
      );
      step.position.set(0, progress * height + 0.08, -length / 2 + progress * length);
      group.add(step);
    }

    [-1, 1].forEach((side) => {
      const rail = new THREE.Mesh(
        new THREE.BoxGeometry(0.06, height, length),
        material(0xded2a0, { roughness: 0.58, opacity: 0.62 }),
      );
      rail.position.set(side * width * 0.55, height / 2, 0);
      rail.rotation.x = Math.atan2(height, length);
      group.add(rail);
    });

    const shaft = new THREE.Mesh(
      new THREE.BoxGeometry(width + 0.25, height, length + 0.2),
      material(0xffd166, { roughness: 0.7, opacity: 0.08 }),
    );
    shaft.position.y = height / 2;
    group.add(shaft);
    return group;
  }

  _gatehouseStairwell(item, mapper) {
    const attrs = item.attributes || {};
    const floorElevation = Number(attrs.floor_elevation_m || 0);
    const topElevation = Number(attrs.connects_to_elevation_m || floorElevation + 5.5);
    const height = Math.max(topElevation - floorElevation, 1.0);
    const length = Math.max(Number(attrs.length_m || 4.8), 1.8);
    const width = Math.max(Number(attrs.width_m || 1.6), 0.8);
    const group = new THREE.Group();
    group.position.copy(mapper.toVector3(item.geometry?.position, floorElevation));
    group.rotation.y = THREE.MathUtils.degToRad(-(item.orientation?.angle_deg || 0));
    group.userData = { selectable: true, entity: item, kind: "office" };

    const connector = new THREE.Mesh(
      new THREE.BoxGeometry(Math.min(width * 0.72, 1.1), 0.035, Math.hypot(length, height)),
      material(0xe9d58b, { roughness: 0.68, opacity: 0.34 }),
    );
    connector.position.set(0, height / 2 + 0.06, 0);
    connector.rotation.x = -Math.atan2(height, length);
    group.add(connector);

    const addOpening = (y) => {
      const opening = new THREE.Group();
      const railMaterial = material(0xe9d58b, { roughness: 0.7, opacity: 0.42 });
      [
        { x: 0, z: -length / 2, sx: width, sz: 0.045 },
        { x: 0, z: length / 2, sx: width, sz: 0.045 },
        { x: -width / 2, z: 0, sx: 0.045, sz: length },
        { x: width / 2, z: 0, sx: 0.045, sz: length },
      ].forEach((part) => {
        const rail = new THREE.Mesh(new THREE.BoxGeometry(part.sx, 0.035, part.sz), railMaterial);
        rail.position.set(part.x, y, part.z);
        opening.add(rail);
      });
      group.add(opening);
    };

    addOpening(0.08);
    addOpening(height + 0.08);
    return group;
  }

  _segmentBox(item, mapper, options) {
    const points = item.geometry?.points || [];
    if (points.length < 2) return null;
    const floorElevation = Number(item.attributes?.floor_elevation_m || 0);
    const start = mapper.toVector3(points[0], floorElevation);
    const end = mapper.toVector3(points[1], floorElevation);
    const dx = end.x - start.x;
    const dz = end.z - start.z;
    const length = Math.hypot(dx, dz);
    if (!Number.isFinite(length) || length <= 0.03) return null;
    const height = Math.max(Number(options.height || 2.4), 0.05);
    const width = Math.max(Number(options.width || 0.16), 0.04);
    const center = new THREE.Vector3((start.x + end.x) / 2, floorElevation + height / 2 + (options.yLift || 0), (start.z + end.z) / 2);
    const mesh = new THREE.Mesh(
      new THREE.BoxGeometry(width, height, length),
      material(options.color || 0xbcd9df, { opacity: options.opacity ?? 0.8, roughness: 0.58 }),
    );
    mesh.position.copy(center);
    mesh.rotation.y = Math.atan2(dx, dz);
    mesh.userData = { selectable: true, entity: item, kind: "office" };
    return mesh;
  }

  _conveyor(item, mapper) {
    const attrs = item.attributes || {};
    const floorElevation = Number(attrs.floor_elevation_m || 0);
    const length = Math.max(Number(attrs.length_m || 10), 2);
    const width = Math.max(Number(attrs.width_m || 0.85), 0.45);
    const group = new THREE.Group();
    group.position.copy(mapper.toVector3(item.geometry?.position, floorElevation + 0.18));
    group.rotation.y = THREE.MathUtils.degToRad(-(item.orientation?.angle_deg || 0));
    group.userData = { selectable: true, entity: item, kind: "logistics" };

    const frame = new THREE.Mesh(
      new THREE.BoxGeometry(width + 0.22, 0.18, length),
      material(0x6aa8b8, { roughness: 0.48, metalness: 0.12 }),
    );
    frame.position.y = 0.12;
    group.add(frame);

    const belt = new THREE.Mesh(
      new THREE.BoxGeometry(width, 0.055, length * 0.96),
      material(0x33474c, { roughness: 0.82 }),
    );
    belt.position.y = 0.24;
    group.add(belt);

    const rollerCount = Math.max(Math.floor(length / 0.7), 8);
    for (let i = 0; i < rollerCount; i += 1) {
      const z = -length * 0.44 + (length * 0.88 * i) / Math.max(rollerCount - 1, 1);
      const roller = new THREE.Mesh(
        new THREE.CylinderGeometry(0.035, 0.035, width + 0.12, 12),
        material(0xd6e7e9, { roughness: 0.34, metalness: 0.2 }),
      );
      roller.rotation.z = Math.PI / 2;
      roller.position.set(0, 0.285, z);
      group.add(roller);
    }

    [-1, 1].forEach((side) => {
      const rail = new THREE.Mesh(
        new THREE.BoxGeometry(0.055, 0.28, length),
        material(0x9ed3df, { roughness: 0.5 }),
      );
      rail.position.set(side * (width / 2 + 0.11), 0.34, 0);
      group.add(rail);
    });

    return group;
  }

  _dwsHost(item, mapper) {
    const floorElevation = Number(item.attributes?.floor_elevation_m || 0);
    const group = new THREE.Group();
    group.position.copy(mapper.toVector3(item.geometry?.position, floorElevation));
    group.rotation.y = THREE.MathUtils.degToRad(-(item.orientation?.angle_deg || 0));
    group.userData = { selectable: true, entity: item, kind: "logistics" };

    const pedestal = new THREE.Mesh(new THREE.BoxGeometry(0.55, 0.72, 0.42), material(0x40545b, { roughness: 0.62 }));
    pedestal.position.y = 0.36;
    group.add(pedestal);

    const host = new THREE.Mesh(new THREE.BoxGeometry(0.38, 0.34, 0.32), material(0x151f24, { roughness: 0.7 }));
    host.position.set(-0.08, 0.92, 0);
    group.add(host);

    const screen = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.34, 0.035), material(0x7ee6ff, { roughness: 0.32, opacity: 0.86 }));
    screen.position.set(0.05, 1.22, -0.19);
    screen.rotation.x = THREE.MathUtils.degToRad(-8);
    group.add(screen);

    const scanner = new THREE.Mesh(new THREE.BoxGeometry(0.62, 0.08, 0.08), material(0xffcf6a, { roughness: 0.45 }));
    scanner.position.set(0, 1.45, 0.08);
    group.add(scanner);

    return group;
  }
}

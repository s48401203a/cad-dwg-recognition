import * as THREE from "three";

const VEHICLE_COLORS = {
  box_4_2: 0x6fb7d8,
  box_9_6: 0x5fbf9a,
  semi_trailer_17_5: 0x9bd7ef,
  container_61ft: 0xd8b46f,
  cad_parking_bay: 0x9bd7ef,
};
const DEFAULT_SPOTLIGHT_MODEL_SCALE = 2.0;
const MIN_SPOTLIGHT_MODEL_SCALE = 1.0;
const MAX_SPOTLIGHT_MODEL_SCALE = 3.0;
const SPOTLIGHT_VISUAL_SIZE_BOOST = 2.0;

function mat(color, opacity = 1, metalness = 0.04) {
  return new THREE.MeshStandardMaterial({
    color,
    roughness: 0.62,
    metalness,
    transparent: opacity < 1,
    opacity,
    side: THREE.DoubleSide,
    depthWrite: opacity >= 0.98,
  });
}

export class VehicleRenderer {
  render(parkingSpaces, mapper) {
    const group = new THREE.Group();
    parkingSpaces.forEach((space) => {
      group.add(this._parkingBay(space, mapper));
      group.add(this._vehicle(space, mapper));
    });
    return group;
  }

  renderSpotlights(fixtures, mapper, modelScaleMultiplier = DEFAULT_SPOTLIGHT_MODEL_SCALE) {
    const group = new THREE.Group();
    const visualScale = this._visualScale(modelScaleMultiplier) * SPOTLIGHT_VISUAL_SIZE_BOOST;
    fixtures.forEach((fixture) => group.add(this._spotlight(fixture, mapper, visualScale)));
    return group;
  }

  _parkingBay(space, mapper) {
    const points = space.geometry?.points || [];
    const group = new THREE.Group();
    if (points.length < 3) return group;
    const groundY = this._vehicleGroundElevation(space);
    const shape = new THREE.Shape(points.map((point) => {
      const mapped = mapper.toXZ(point);
      return new THREE.Vector2(mapped.x, mapped.z);
    }));
    const fill = new THREE.Mesh(
      new THREE.ShapeGeometry(shape).rotateX(-Math.PI / 2),
      new THREE.MeshBasicMaterial({ color: 0xf4b43a, transparent: true, opacity: 0.05, side: THREE.DoubleSide, depthWrite: false }),
    );
    fill.position.y = groundY + 0.035;
    fill.userData = { selectable: true, entity: space, kind: "parking" };
    group.add(fill);

    const vectors = points.map((point) => {
      const mapped = mapper.toXZ(point);
      return new THREE.Vector3(mapped.x, groundY + 0.065, mapped.z);
    });
    vectors.push(vectors[0].clone());
    const outline = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints(vectors),
      new THREE.LineBasicMaterial({ color: 0xf4b43a, transparent: true, opacity: 0.72 }),
    );
    outline.userData = { selectable: true, entity: space, kind: "parking" };
    group.add(outline);
    return group;
  }

  _vehicle(space, mapper) {
    const attrs = space.attributes || {};
    const group = new THREE.Group();
    const center = this._center(space.geometry?.points || []);
    if (!center) return group;
    const length = Number(attrs.vehicle_length_m || 9.6);
    const width = Number(attrs.vehicle_width_m || 2.45);
    const height = Number(attrs.vehicle_height_m || 3.4);
    const type = attrs.vehicle_type || "box_9_6";
    const color = VEHICLE_COLORS[type] || 0x6fb7d8;
    const base = mapper.toVector3(center, 0);
    group.position.set(base.x, this._vehicleGroundElevation(space), base.z);
    group.rotation.y = this._yawFromAngle(space.orientation?.angle_deg || 0);
    group.userData = { selectable: true, entity: space, kind: "vehicle" };

    const cabLength = type === "container_61ft" || type === "semi_trailer_17_5" ? 3.1 : Math.min(2.0, length * 0.28);
    const cargoLength = Math.max(length - cabLength, length * 0.55);
    const cargo = new THREE.Mesh(
      new THREE.BoxGeometry(cargoLength, height, width),
      mat(color, 0.90, 0.08),
    );
    cargo.position.set(-cabLength / 2, 0.38 + height / 2, 0);
    group.add(cargo);

    const cab = new THREE.Mesh(
      new THREE.BoxGeometry(cabLength, Math.min(height * 0.74, 2.7), width * 0.9),
      mat(0xe8edf0, 0.96, 0.05),
    );
    cab.position.set(length / 2 - cabLength / 2, 0.38 + Math.min(height * 0.74, 2.7) / 2, 0);
    group.add(cab);

    const wheelMat = mat(0x111416, 1, 0.02);
    const wheelPositions = [
      [-length * 0.34, -width * 0.53],
      [-length * 0.34, width * 0.53],
      [length * 0.26, -width * 0.50],
      [length * 0.26, width * 0.50],
    ];
    if (type === "container_61ft") {
      wheelPositions.push([-length * 0.08, -width * 0.53], [-length * 0.08, width * 0.53]);
    }
    wheelPositions.forEach(([x, z]) => {
      const wheel = new THREE.Mesh(new THREE.CylinderGeometry(0.28, 0.28, 0.18, 14), wheelMat);
      wheel.rotation.x = Math.PI / 2;
      wheel.position.set(x, 0.30, z);
      group.add(wheel);
    });
    return group;
  }

  _spotlight(fixture, mapper, modelScale) {
    const group = new THREE.Group();
    const position = fixture.geometry?.position;
    if (!position) return group;
    const attrs = fixture.attributes || {};
    const height = Number(attrs.install_height_m || 3.0);
    const beamLength = Number(attrs.beam_length_m || 7.5);
    const beamAngle = THREE.MathUtils.degToRad(Number(attrs.beam_angle_deg || 36));
    const base = mapper.toVector3(position, height);
    group.position.copy(base);
    group.rotation.y = this._yawFromCadAngle(fixture.orientation?.angle_deg || 0);
    group.userData = { selectable: true, entity: fixture, kind: "fixture" };

    if (height > 0.2) {
      const pole = new THREE.Mesh(
        new THREE.CylinderGeometry(0.04 * modelScale, 0.05 * modelScale, height, 10),
        mat(0x3f4541, 1, 0.18),
      );
      pole.position.y = -height / 2;
      group.add(pole);
      const foot = new THREE.Mesh(
        new THREE.CircleGeometry(0.38 * modelScale, 24),
        new THREE.MeshBasicMaterial({ color: 0xf4b43a, transparent: true, opacity: 0.55, depthWrite: false, side: THREE.DoubleSide }),
      );
      foot.rotation.x = -Math.PI / 2;
      foot.position.y = -height + 0.03;
      group.add(foot);
    }

    const housing = new THREE.Mesh(
      new THREE.BoxGeometry(0.62 * modelScale, 0.34 * modelScale, 0.36 * modelScale),
      new THREE.MeshStandardMaterial({
        color: 0xf4b43a,
        roughness: 0.38,
        metalness: 0.16,
        emissive: 0xb45309,
        emissiveIntensity: 0.35,
      }),
    );
    housing.position.x = 0.18 * modelScale;
    group.add(housing);

    const lens = new THREE.Mesh(
      new THREE.CylinderGeometry(0.16 * modelScale, 0.16 * modelScale, 0.05 * modelScale, 16),
      new THREE.MeshStandardMaterial({
        color: 0xfff3b0,
        roughness: 0.18,
        metalness: 0.04,
        emissive: 0xffd166,
        emissiveIntensity: 0.55,
      }),
    );
    lens.rotation.x = Math.PI / 2;
    lens.position.set(0.18 * modelScale, 0, -0.2 * modelScale);
    group.add(lens);

    const beamRadius = Math.tan(beamAngle / 2) * beamLength;
    const beam = new THREE.Mesh(
      new THREE.CylinderGeometry(beamRadius, 0.1, beamLength, 28, 1, true),
      new THREE.MeshBasicMaterial({ color: 0xffd166, transparent: true, opacity: 0.26, depthWrite: false, side: THREE.DoubleSide }),
    );
    beam.rotation.x = -Math.PI / 2;
    beam.position.z = -beamLength / 2;
    group.add(beam);
    return group;
  }

  _center(points) {
    if (!points.length) return null;
    return {
      x: points.reduce((sum, point) => sum + point.x, 0) / points.length,
      y: points.reduce((sum, point) => sum + point.y, 0) / points.length,
    };
  }

  _vehicleGroundElevation(space) {
    const attrs = space.attributes || {};
    const explicit = Number(attrs.vehicle_ground_elevation_m ?? attrs.yard_ground_elevation_m);
    return Number.isFinite(explicit) ? explicit : 0;
  }

  _yawFromAngle(angleDeg) {
    const angle = THREE.MathUtils.degToRad(Number(angleDeg || 0));
    const dx = Math.sin(angle);
    const dy = -Math.cos(angle);
    return Math.atan2(dy, dx);
  }

  _yawFromCadAngle(angleDeg) {
    return Math.PI + THREE.MathUtils.degToRad(Number(angleDeg || 0));
  }

  _visualScale(value) {
    const numeric = Number(value);
    return Number.isFinite(numeric) ? Math.max(MIN_SPOTLIGHT_MODEL_SCALE, Math.min(numeric, MAX_SPOTLIGHT_MODEL_SCALE)) : DEFAULT_SPOTLIGHT_MODEL_SCALE;
  }
}

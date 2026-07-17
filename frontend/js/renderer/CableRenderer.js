import * as THREE from "three";

export class CableRenderer {
  render(cables, mapper) {
    const group = new THREE.Group();
    const parallelContext = this._parallelContext(cables);
    cables.forEach((cable) => {
      const points = cable.geometry?.points || [];
      if (points.length < 2) return;

      const routeHeight = this.heightFor(cable);
      const parallelOffset = this._parallelOffsetFor(cable, parallelContext);
      const material = new THREE.LineBasicMaterial({
        color: this.colorFor(cable.type),
        transparent: true,
        opacity: cable.attributes?.source_kind === "cabinet_link_inferred" ? 0.96 : 0.86,
      });
      const vectors = this._offsetPolyline(
        points.map((point) => mapper.toVector3(point, routeHeight)),
        parallelOffset,
      );
      const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(vectors), material);
      line.userData = { selectable: true, entity: cable, kind: "cable" };
      group.add(line);

      if (cable.attributes?.terminates_inside_cabinet) {
        this._addCabinetDrops(group, cable, mapper, material, routeHeight, points, vectors);
      }
    });
    return group;
  }

  _addCabinetDrops(group, cable, mapper, material, routeHeight, points, routeVectors) {
    const first = points[0];
    const last = points[points.length - 1];
    const sourceHeight = Number(cable.attributes?.source_entry_height_m || routeHeight);
    const targetHeight = Number(cable.attributes?.target_entry_height_m || routeHeight);
    [
      [first, sourceHeight, routeVectors[0]],
      [last, targetHeight, routeVectors[routeVectors.length - 1]],
    ].forEach(([point, entryHeight, routeVector]) => {
      if (!point || Math.abs(entryHeight - routeHeight) < 0.03) return;
      const entryVector = mapper.toVector3(point, entryHeight);
      entryVector.x = routeVector.x;
      entryVector.z = routeVector.z;
      const drop = new THREE.Line(
        new THREE.BufferGeometry().setFromPoints([
          routeVector,
          entryVector,
        ]),
        material.clone(),
      );
      drop.userData = { selectable: true, entity: cable, kind: "cable" };
      group.add(drop);
    });
  }

  _parallelContext(cables) {
    const context = new Map();
    (cables || []).forEach((cable) => {
      const total = this._parallelTotalFor(cable);
      const rawIndex = Number(cable.attributes?.parallel_index);
      if (total < 2 || !Number.isFinite(rawIndex)) return;
      const key = this._parallelKeyFor(cable);
      const entry = context.get(key) || { hasZeroIndex: false };
      entry.hasZeroIndex = entry.hasZeroIndex || rawIndex === 0;
      context.set(key, entry);
    });
    return context;
  }

  _parallelOffsetFor(cable, context) {
    const total = this._parallelTotalFor(cable);
    const rawIndex = Number(cable.attributes?.parallel_index);
    if (total < 2 || !Number.isFinite(rawIndex)) return null;

    const key = this._parallelKeyFor(cable);
    const zeroBased = context.get(key)?.hasZeroIndex;
    const normalizedIndex = zeroBased ? rawIndex : rawIndex - 1;
    const index = Math.max(0, Math.min(total - 1, Math.trunc(normalizedIndex)));
    const spacing = 0.055;
    const amount = (index - (total - 1) / 2) * spacing;
    if (Math.abs(amount) < 0.0001) return null;
    return amount;
  }

  _parallelTotalFor(cable) {
    const attributes = cable.attributes || {};
    const parallelTotal = Number(attributes.parallel_total);
    const bundleCount = Number(attributes.bundle_count);
    const total = Number.isFinite(parallelTotal) && parallelTotal > 1 ? parallelTotal : bundleCount;
    return Number.isFinite(total) && total > 1 ? Math.trunc(total) : 1;
  }

  _parallelKeyFor(cable) {
    const attributes = cable.attributes || {};
    const explicitKey =
      attributes.bundle_id ||
      attributes.bundle_key ||
      attributes.bundle_group ||
      attributes.bundle_role_id;
    if (explicitKey) return `bundle:${explicitKey}`;

    const points = cable.geometry?.points || [];
    const signature = points
      .map((point) => `${Math.round((point?.x || 0) * 1000) / 1000},${Math.round((point?.y || 0) * 1000) / 1000}`)
      .join("|");
    const reversed = signature.split("|").reverse().join("|");
    return `${cable.type || "cable"}:${signature < reversed ? signature : reversed}`;
  }

  _offsetPolyline(vectors, parallelOffset) {
    if (!parallelOffset || vectors.length < 2) return vectors;
    return vectors.map((vector, index) => {
      const previous = vectors[index - 1];
      const next = vectors[index + 1];
      const before = previous ? this._segmentNormal(previous, vector) : null;
      const after = next ? this._segmentNormal(vector, next) : null;
      const normal = this._averageNormal(before, after);
      return vector.clone().addScaledVector(normal, parallelOffset);
    });
  }

  _segmentNormal(from, to) {
    const dx = to.x - from.x;
    const dz = to.z - from.z;
    const length = Math.hypot(dx, dz);
    if (length < 0.0001) return null;
    return new THREE.Vector3(-dz / length, 0, dx / length);
  }

  _averageNormal(before, after) {
    if (before && after) {
      const normal = before.clone().add(after);
      if (normal.lengthSq() > 0.0001) return normal.normalize();
    }
    return before || after || new THREE.Vector3(1, 0, 0);
  }

  colorFor(type) {
    if (type === "cable.trunk") return 0xf4b43a;
    if (type === "cable.fiber") return 0xb79cff;
    if (type === "cable.security") return 0xff4d4d;
    if (type === "cable.network") return 0x22d3ee;
    if (type === "cable.cabinet_power") return 0x7ddc83;
    if (type === "cable.spotlight_power") return 0xffc857;
    return 0x8bdde8;
  }

  heightFor(cable) {
    const explicit = Number(cable.attributes?.height_m);
    if (Number.isFinite(explicit) && explicit > 0) return explicit;
    if (cable.type === "cable.cabinet_power") return 2.8;
    if (cable.type === "cable.spotlight_power") return 3.0;
    return cable.type === "cable.trunk" ? 3.1 : 0.12;
  }
}

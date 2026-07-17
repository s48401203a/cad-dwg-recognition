import * as THREE from "three";

export class CoordMapper {
  constructor(extents) {
    const min = extents?.min || { x: 0, y: 0 };
    const max = extents?.max || { x: 10000, y: 10000 };
    this.scale = 0.001;
    this.center = {
      x: ((min.x || 0) + (max.x || 0)) / 2,
      y: ((min.y || 0) + (max.y || 0)) / 2,
    };
    this.width = Math.max(((max.x || 0) - (min.x || 0)) * this.scale, 20);
    this.depth = Math.max(((max.y || 0) - (min.y || 0)) * this.scale, 20);
    this.floorHeight = 0;
  }

  toXZ(point) {
    return {
      x: ((point?.x || 0) - this.center.x) * this.scale,
      z: -((point?.y || 0) - this.center.y) * this.scale,
    };
  }

  toVector3(point, y = 0) {
    const mapped = this.toXZ(point);
    return new THREE.Vector3(mapped.x, y + this.floorHeight, mapped.z);
  }

  pointsToVectors(points, y = 0) {
    return (points || []).map((point) => this.toVector3(point, y));
  }
}

import { CSS2DObject } from "three/addons/renderers/CSS2DRenderer.js";

export class LabelRenderer {
  create(text, position, type = "") {
    const div = document.createElement("div");
    div.className = `label ${this.classFor(type)}`;
    div.dataset.cadLabel = "true";
    div.textContent = text;
    const label = new CSS2DObject(div);
    label.position.copy(position);
    return label;
  }

  classFor(type) {
    if (type === "network.ap") return "ap";
    if (type === "security.camera.fisheye" || type === "security.camera.dome") return "fisheye";
    if (type.startsWith("security.camera")) return "camera";
    return "";
  }
}

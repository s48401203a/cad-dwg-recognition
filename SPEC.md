# DWG 图纸识别 + Three.js 3D 预览工具 — 技术方案

> 本文档是 Codex 执行用的完整技术规格。请按「开发阶段」顺序实现，每阶段完成后验证再继续。

---

## 一、项目目标

用户上传 DWG/DXF 文件 → 后端自动用 ODA File Converter 转换为 DXF → ezdxf 解析图层/块/文字/几何实体 → 规则引擎识别弱电设备/线路/区域 → 生成 semantic.json → 前端 Three.js 自动生成可交互 2.5D 预览模型。

**核心流程（5步）：**
```
上传 DWG/DXF → ODA FC 转 DXF → ezdxf 解析 → 规则识别 → Three.js 渲染
```

---

## 二、技术栈

| 层 | 技术 | 版本要求 |
|---|---|---|
| 后端框架 | Python FastAPI | >= 0.111 |
| DXF 解析 | ezdxf | >= 1.4.0 |
| DWG 转换 | ODA File Converter CLI | 任意版本（需本地安装） |
| 规则配置 | PyYAML | >= 6.0 |
| 几何计算 | Shapely | >= 2.0 |
| 前端框架 | Vue 3 + Vite | Vue >= 3.4 |
| 3D 渲染 | Three.js | >= 0.167 |
| 状态管理 | Pinia | >= 2.1 |
| HTTP 客户端 | Axios | >= 1.7 |

---

## 三、目录结构

```
project/
├── backend/
│   ├── main.py                    # FastAPI 入口
│   ├── api/
│   │   ├── upload.py              # POST /api/upload
│   │   └── parse.py               # POST /api/parse
│   ├── parser/
│   │   ├── dwg_converter.py       # ODA FC CLI 封装
│   │   ├── dxf_reader.py          # ezdxf 实体遍历
│   │   └── entity_extractor.py    # 实体标准化提取
│   ├── semantic/
│   │   ├── rule_engine.py         # mapping.yaml 驱动分类器
│   │   ├── geometry_utils.py      # 闭合多边形、点在区域内
│   │   └── models.py              # Pydantic 数据模型
│   ├── config/
│   │   └── mapping.yaml           # 识别规则（见第七节）
│   └── requirements.txt
│
├── frontend/
│   ├── index.html
│   ├── vite.config.js
│   ├── src/
│   │   ├── App.vue
│   │   ├── api/cadApi.js          # 后端接口封装
│   │   ├── stores/cad.js          # Pinia store
│   │   ├── components/
│   │   │   ├── UploadZone.vue     # 文件上传区域
│   │   │   ├── ThreeViewer.vue    # Three.js 画布组件
│   │   │   ├── LayerPanel.vue     # 左侧图层/系统过滤
│   │   │   └── DevicePanel.vue    # 右侧设备属性弹窗
│   │   └── renderer/
│   │       ├── SceneBuilder.js    # 场景总构建器
│   │       ├── DeviceFactory.js   # 设备 3D 对象工厂
│   │       ├── AreaRenderer.js    # 区域/车位平面渲染
│   │       ├── CableRenderer.js   # 线路 LineSegments
│   │       └── CoordMapper.js     # CAD mm → Three.js m
│   └── package.json
│
└── mapping.yaml                   # 顶层规则（与 backend/config/mapping.yaml 相同）
```

---

## 四、后端实现规格

### 4.1 main.py

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api import upload, parse
import os

app = FastAPI(title="CAD DWG Preview API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(upload.router, prefix="/api")
app.include_router(parse.router, prefix="/api")

# 上传文件存储目录
UPLOAD_DIR = "./uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)
```

---

### 4.2 api/upload.py

**接口：** `POST /api/upload`

**请求：** `multipart/form-data`，字段名 `file`，接受 `.dwg` 和 `.dxf`

**响应：**
```json
{
  "file_id": "uuid4字符串",
  "original_name": "building.dwg",
  "format": "dwg",
  "dxf_ready": true,
  "message": "已转换为DXF"
}
```

**实现要求：**
1. 保存上传文件到 `./uploads/{file_id}/original.{ext}`
2. 若是 `.dwg`，调用 `DwgConverter.convert()` 转为 DXF，保存为 `./uploads/{file_id}/converted.dxf`
3. 若已是 `.dxf`，直接保存为 `./uploads/{file_id}/converted.dxf`
4. 返回 `file_id`

---

### 4.3 api/parse.py

**接口：** `POST /api/parse`

**请求体：**
```json
{ "file_id": "uuid4字符串" }
```

**响应：** 完整的 `semantic.json`（见第六节）

**实现要求：**
1. 读取 `./uploads/{file_id}/converted.dxf`
2. 调用 `DxfReader.read()` 提取原始实体列表
3. 调用 `EntityExtractor.extract()` 标准化每个实体
4. 调用 `RuleEngine.classify()` 识别语义类型
5. 调用 `GeometryUtils.associate_texts()` 将文字关联到最近区域
6. 组装并返回 semantic.json

---

### 4.4 parser/dwg_converter.py

> **已确认安装路径：** `C:\Program Files\ODA\ODAFileConverter 27.1.0\ODAFileConverter.exe`
> 使用 ezdxf 内置的 `odafc` addon，比手写 subprocess 更稳定。

```python
import os
from pathlib import Path
import ezdxf
from ezdxf.addons import odafc

# 配置 ODA FC 路径（支持环境变量覆盖）
_ODA_DEFAULT = r"C:\Program Files\ODA\ODAFileConverter 27.1.0\ODAFileConverter.exe"
odafc.win_exec_path = os.environ.get("ODA_FC_PATH", _ODA_DEFAULT)


class DwgConverter:
    @staticmethod
    def is_available() -> bool:
        return Path(odafc.win_exec_path).exists()

    @staticmethod
    def convert(input_dwg: Path, output_dir: Path) -> Path:
        """
        将 DWG 转换为 DXF R2018 格式，返回转换后的 DXF 路径。
        使用 ezdxf odafc addon 调用 ODA File Converter。
        """
        if not DwgConverter.is_available():
            raise RuntimeError(
                f"未找到 ODA File Converter: {odafc.win_exec_path}\n"
                "安装命令: winget install ODA.ODAFileConverter"
            )

        output_dir.mkdir(parents=True, exist_ok=True)
        output_dxf = output_dir / (input_dwg.stem + ".dxf")

        # ezdxf odafc.convert 直接读取 DWG 并返回 ezdxf document
        doc = odafc.readfile(str(input_dwg))
        doc.saveas(str(output_dxf))
        return output_dxf
```

---

### 4.5 parser/dxf_reader.py

```python
import ezdxf
from pathlib import Path
from typing import Any

class DxfReader:
    @staticmethod
    def read(dxf_path: Path) -> list[dict[str, Any]]:
        """
        读取 DXF 文件，返回标准化原始实体列表。
        支持实体类型：INSERT、LINE、LWPOLYLINE、POLYLINE、TEXT、MTEXT、CIRCLE、ARC
        """
        doc = ezdxf.readfile(str(dxf_path))
        msp = doc.modelspace()

        # 读取单位（$INSUNITS：0=无单位,1=英寸,4=mm,5=cm,6=m）
        insunits = doc.header.get("$INSUNITS", 4)
        unit_to_mm = {0: 1.0, 1: 25.4, 4: 1.0, 5: 10.0, 6: 1000.0}
        scale = unit_to_mm.get(insunits, 1.0)

        entities = []
        for entity in msp:
            raw = DxfReader._parse_entity(entity, scale)
            if raw:
                entities.append(raw)

        return entities

    @staticmethod
    def _parse_entity(entity, scale: float) -> dict | None:
        etype = entity.dxftype()
        layer = entity.dxf.get("layer", "0")
        color = entity.dxf.get("color", 256)  # 256=随层

        base = {
            "entity_id": entity.dxf.handle,
            "type": etype,
            "layer": layer,
            "color": color,
        }

        if etype == "INSERT":
            pos = entity.dxf.insert
            return {**base,
                "block_name": entity.dxf.name,
                "position": {"x": pos.x * scale, "y": pos.y * scale},
                "rotation": entity.dxf.get("rotation", 0.0),
                "attributes": {
                    attr.dxf.tag: attr.dxf.text
                    for attr in entity.attribs
                } if hasattr(entity, "attribs") else {},
            }

        elif etype in ("LINE",):
            s = entity.dxf.start
            e = entity.dxf.end
            return {**base,
                "start": {"x": s.x * scale, "y": s.y * scale},
                "end":   {"x": e.x * scale, "y": e.y * scale},
            }

        elif etype == "LWPOLYLINE":
            return {**base,
                "points": [{"x": p[0] * scale, "y": p[1] * scale}
                           for p in entity.get_points()],
                "closed": entity.closed,
            }

        elif etype == "TEXT":
            pos = entity.dxf.insert
            return {**base,
                "text": entity.dxf.text,
                "position": {"x": pos.x * scale, "y": pos.y * scale},
                "height": entity.dxf.get("height", 300) * scale,
            }

        elif etype == "MTEXT":
            pos = entity.dxf.insert
            return {**base,
                "text": entity.plain_mtext(),
                "position": {"x": pos.x * scale, "y": pos.y * scale},
                "height": entity.dxf.get("char_height", 300) * scale,
            }

        elif etype == "CIRCLE":
            c = entity.dxf.center
            return {**base,
                "center": {"x": c.x * scale, "y": c.y * scale},
                "radius": entity.dxf.radius * scale,
            }

        elif etype == "ARC":
            c = entity.dxf.center
            return {**base,
                "center": {"x": c.x * scale, "y": c.y * scale},
                "radius": entity.dxf.radius * scale,
                "start_angle": entity.dxf.start_angle,
                "end_angle": entity.dxf.end_angle,
            }

        return None  # 跳过不支持的实体类型
```

---

### 4.6 semantic/rule_engine.py

```python
import yaml
import re
from pathlib import Path
from typing import Any

MAPPING_PATH = Path(__file__).parent.parent / "config" / "mapping.yaml"

class RuleEngine:
    def __init__(self):
        with open(MAPPING_PATH, encoding="utf-8") as f:
            self.rules = yaml.safe_load(f)

    def classify(self, entity: dict[str, Any]) -> dict[str, Any]:
        """
        对单个实体进行语义分类。
        返回包含 semantic_type 和 confidence 的字典。
        """
        scores: dict[str, float] = {}

        layer = entity.get("layer", "").upper()
        block_name = entity.get("block_name", "").upper()
        text = entity.get("text", "").upper()

        # 图层匹配（权重 0.35）
        layer_type, layer_conf = self._match_keywords(
            layer, self.rules.get("layer_rules", {}))
        if layer_type:
            scores[layer_type] = scores.get(layer_type, 0) + layer_conf * 0.35

        # 块名匹配（权重 0.45）
        block_type, block_conf = self._match_keywords(
            block_name, self.rules.get("block_rules", {}))
        if block_type:
            scores[block_type] = scores.get(block_type, 0) + block_conf * 0.45

        # 文字匹配（权重 0.20）
        text_type, text_conf = self._match_keywords(
            text, self.rules.get("text_rules", {}))
        if text_type:
            scores[text_type] = scores.get(text_type, 0) + text_conf * 0.20

        if not scores:
            return {**entity, "semantic_type": "unknown", "confidence": 0.0}

        best_type = max(scores, key=scores.__getitem__)
        confidence = min(scores[best_type], 1.0)

        return {
            **entity,
            "semantic_type": best_type,
            "confidence": round(confidence, 3),
            "review_needed": confidence < 0.65,
        }

    def _match_keywords(self, text: str, rules: dict) -> tuple[str | None, float]:
        best_type = None
        best_conf = 0.0
        for rule_type, rule_cfg in rules.items():
            for kw in rule_cfg.get("keywords", []):
                if kw.upper() in text:
                    conf = rule_cfg.get("confidence", 0.8)
                    if conf > best_conf:
                        best_type = rule_type
                        best_conf = conf
        return best_type, best_conf
```

---

### 4.7 semantic/geometry_utils.py

```python
import math
from shapely.geometry import Point, Polygon

def is_closed_polygon(entity: dict) -> bool:
    return (entity.get("type") == "LWPOLYLINE"
            and entity.get("closed", False)
            and len(entity.get("points", [])) >= 4)

def calc_area_m2(points: list[dict]) -> float:
    if len(points) < 3:
        return 0.0
    poly = Polygon([(p["x"], p["y"]) for p in points])
    return poly.area / 1e6  # mm² → m²

def point_in_polygon(px: float, py: float, points: list[dict]) -> bool:
    poly = Polygon([(p["x"], p["y"]) for p in points])
    return poly.contains(Point(px, py))

def nearest_text_within(position: dict, texts: list[dict], max_dist_mm: float = 5000) -> str | None:
    """返回距离 position 最近且在 max_dist_mm 内的文字内容。"""
    px, py = position["x"], position["y"]
    best_text = None
    best_dist = float("inf")
    for t in texts:
        tp = t.get("position", {})
        dist = math.hypot(px - tp.get("x", 0), py - tp.get("y", 0))
        if dist < max_dist_mm and dist < best_dist:
            best_dist = dist
            best_text = t.get("text", "")
    return best_text

def calc_bounding_box(entities: list[dict]) -> dict:
    xs, ys = [], []
    for e in entities:
        if "position" in e:
            xs.append(e["position"]["x"])
            ys.append(e["position"]["y"])
        if "points" in e:
            for p in e["points"]:
                xs.append(p["x"]); ys.append(p["y"])
        if "start" in e:
            xs.append(e["start"]["x"]); ys.append(e["start"]["y"])
            xs.append(e["end"]["x"]); ys.append(e["end"]["y"])
    if not xs:
        return {"min": {"x": 0, "y": 0}, "max": {"x": 1, "y": 1}}
    return {"min": {"x": min(xs), "y": min(ys)},
            "max": {"x": max(xs), "y": max(ys)}}
```

---

### 4.8 semantic/models.py（Pydantic）

```python
from pydantic import BaseModel
from typing import Any

class Point2D(BaseModel):
    x: float
    y: float

class DrawingMeta(BaseModel):
    source_file: str
    dxf_version: str = ""
    converted_from_dwg: bool = False
    extents: dict
    unit: str = "mm"

class CoordinateSystem(BaseModel):
    unit: str = "mm"
    scale_to_meters: float = 0.001
    three_js_mapping: str = "x→x, y→-z, elevation=0"

class Device(BaseModel):
    id: str
    type: str
    subtype: str | None = None
    source_entity_id: str
    original_layer: str
    original_block_name: str = ""
    confidence: float
    review_needed: bool = False
    geometry: dict
    orientation: dict = {}
    attributes: dict = {}
    connections: list[str] = []

class Cable(BaseModel):
    id: str
    type: str
    source_entity_id: str
    original_layer: str
    confidence: float
    geometry: dict
    from_device: str | None = None
    to_device: str | None = None

class Area(BaseModel):
    id: str
    type: str
    label: str = ""
    source_entity_id: str
    original_layer: str
    confidence: float
    geometry: dict
    area_m2: float = 0.0

class ParkingSpace(BaseModel):
    id: str
    type: str
    label: str = ""
    source_entity_id: str
    original_layer: str
    confidence: float
    geometry: dict

class Annotation(BaseModel):
    id: str
    entity_type: str
    content: str
    position: dict
    original_layer: str

class SemanticDocument(BaseModel):
    schema_version: str = "1.0.0"
    drawing_meta: DrawingMeta
    coordinate_system: CoordinateSystem
    devices: list[Device] = []
    cables: list[Cable] = []
    areas: list[Area] = []
    parking_spaces: list[ParkingSpace] = []
    annotations: list[Annotation] = []
```

---

### 4.9 完整 parse 逻辑（api/parse.py）

```python
from fastapi import APIRouter, HTTPException
from pathlib import Path
from parser.dxf_reader import DxfReader
from semantic.rule_engine import RuleEngine
from semantic.geometry_utils import (
    is_closed_polygon, calc_area_m2, calc_bounding_box, nearest_text_within
)
import uuid

router = APIRouter()
engine = RuleEngine()

UPLOAD_DIR = Path("./uploads")

@router.post("/parse")
def parse_file(body: dict):
    file_id = body.get("file_id")
    dxf_path = UPLOAD_DIR / file_id / "converted.dxf"
    if not dxf_path.exists():
        raise HTTPException(404, "文件未找到，请先上传")

    raw_entities = DxfReader.read(dxf_path)
    classified = [engine.classify(e) for e in raw_entities]

    # 分离文字实体（用于区域文字关联）
    texts = [e for e in classified if e["type"] in ("TEXT", "MTEXT")]

    extents = calc_bounding_box(classified)

    devices, cables, areas, parkings, annotations = [], [], [], [], []

    dev_idx = cab_idx = area_idx = park_idx = ann_idx = 0

    for e in classified:
        stype = e.get("semantic_type", "unknown")
        conf = e.get("confidence", 0.0)

        # 设备（INSERT 块）
        if e["type"] == "INSERT" and stype != "unknown":
            devices.append({
                "id": f"dev_{dev_idx:04d}",
                "type": stype,
                "source_entity_id": e["entity_id"],
                "original_layer": e["layer"],
                "original_block_name": e.get("block_name", ""),
                "confidence": conf,
                "review_needed": e.get("review_needed", False),
                "geometry": {"type": "Point", "position": e["position"]},
                "orientation": {"angle_deg": e.get("rotation", 0.0)},
                "attributes": e.get("attributes", {}),
            })
            dev_idx += 1

        # 线路（LINE 或开放 LWPOLYLINE，弱电/网络/监控图层）
        elif e["type"] in ("LINE", "LWPOLYLINE") and not e.get("closed", False) \
             and stype.startswith("cable"):
            pts = []
            if e["type"] == "LINE":
                pts = [e["start"], e["end"]]
            else:
                pts = e.get("points", [])
            cables.append({
                "id": f"cab_{cab_idx:04d}",
                "type": stype,
                "source_entity_id": e["entity_id"],
                "original_layer": e["layer"],
                "confidence": conf,
                "geometry": {"type": "Polyline", "points": pts},
            })
            cab_idx += 1

        # 区域（闭合多段线）
        elif is_closed_polygon(e) and stype.startswith("area"):
            pts = e.get("points", [])
            center = {
                "x": sum(p["x"] for p in pts) / len(pts),
                "y": sum(p["y"] for p in pts) / len(pts),
            }
            label = nearest_text_within(center, texts) or stype
            areas.append({
                "id": f"area_{area_idx:04d}",
                "type": stype,
                "label": label,
                "source_entity_id": e["entity_id"],
                "original_layer": e["layer"],
                "confidence": conf,
                "geometry": {"type": "Polygon", "points": pts, "closed": True},
                "area_m2": calc_area_m2(pts),
            })
            area_idx += 1

        # 停车位（闭合矩形，特定宽高比）
        elif is_closed_polygon(e) and stype.startswith("parking"):
            pts = e.get("points", [])
            parkings.append({
                "id": f"park_{park_idx:04d}",
                "type": stype,
                "source_entity_id": e["entity_id"],
                "original_layer": e["layer"],
                "confidence": conf,
                "geometry": {"type": "Polygon", "points": pts, "closed": True},
            })
            park_idx += 1

        # 文字标注
        elif e["type"] in ("TEXT", "MTEXT"):
            annotations.append({
                "id": f"ann_{ann_idx:04d}",
                "entity_type": e["type"],
                "content": e.get("text", ""),
                "position": e.get("position", {}),
                "original_layer": e["layer"],
            })
            ann_idx += 1

    return {
        "schema_version": "1.0.0",
        "drawing_meta": {
            "source_file": str(dxf_path.name),
            "converted_from_dwg": (UPLOAD_DIR / file_id / "original.dwg").exists(),
            "extents": extents,
            "unit": "mm",
        },
        "coordinate_system": {
            "unit": "mm",
            "scale_to_meters": 0.001,
            "three_js_mapping": "x→x, y→-z, elevation=0",
        },
        "devices": devices,
        "cables": cables,
        "areas": areas,
        "parking_spaces": parkings,
        "annotations": annotations,
    }
```

---

### 4.10 requirements.txt

```
ezdxf>=1.4.0
fastapi>=0.111.0
uvicorn[standard]>=0.30.0
python-multipart>=0.0.9
pyyaml>=6.0
shapely>=2.0.0
aiofiles>=23.0.0
```

---

## 五、配置文件 mapping.yaml

```yaml
version: "1.0"

layer_rules:
  security.camera:
    keywords: [CCTV, 监控, CAM, 摄像头, 摄像, CAMERA, IPC]
    confidence: 0.88
  security.access_control:
    keywords: [门禁, ACCESS, CTRL, 读卡, READER]
    confidence: 0.86
  network.ap:
    keywords: [AP, WIFI, WL, 无线, WIRELESS, WAP]
    confidence: 0.84
  network.switch:
    keywords: [SW, SWITCH, 交换机, HUB]
    confidence: 0.84
  network.cabinet:
    keywords: [机柜, IDF, MDF, RACK, 弱电间]
    confidence: 0.88
  cable.network:
    keywords: [网线, CAT5, CAT6, UTP, RJ45, 数据线]
    confidence: 0.80
  cable.fiber:
    keywords: [光纤, FIBER, FO, 光缆]
    confidence: 0.85
  cable.trunk:
    keywords: [桥架, TRAY, 线槽, 管线, CONDUIT]
    confidence: 0.78
  area.office:
    keywords: [办公, OFFICE, OFC, 行政]
    confidence: 0.80
  area.warehouse:
    keywords: [仓库, 货仓, 库房, WAREHOUSE, STORAGE]
    confidence: 0.83
  area.parking:
    keywords: [停车, 车位, PARKING, PARK, 货车, TRUCK]
    confidence: 0.80
  broadcast:
    keywords: [广播, SPEAKER, PA, 音箱]
    confidence: 0.82
  alarm:
    keywords: [报警, 烟感, FIRE, ALARM, SMOKE, 消防]
    confidence: 0.82

block_rules:
  security.camera:
    keywords: [CAM, CCTV, 摄像头, IPC, CAMERA, DOME, PTZ, BULLET]
    confidence: 0.94
  network.ap:
    keywords: [AP, WAP, WIFI, 无线AP, ACCESS_POINT]
    confidence: 0.94
  network.switch:
    keywords: [SW, SWITCH, 交换机, L2SW, L3SW]
    confidence: 0.92
  network.cabinet:
    keywords: [机柜, RACK, CABINET, IDF, MDF]
    confidence: 0.92
  network.outlet:
    keywords: [信息点, RJ45, DATA, 网口, 信息插座, IO]
    confidence: 0.90
  security.access_control:
    keywords: [门禁, READER, ACCESS, CTRL, 读卡器]
    confidence: 0.92
  broadcast.speaker:
    keywords: [广播, SPEAKER, PA, 音箱]
    confidence: 0.86
  alarm.detector:
    keywords: [报警, ALARM, SMOKE, 烟感, 探头]
    confidence: 0.86
  weak_electric.box:
    keywords: [弱电箱, 综合箱, 弱电间, 弱电柜]
    confidence: 0.86

text_rules:
  area.office:
    keywords: [办公区, 办公室, 行政区, OFFICE]
    confidence: 0.78
  area.warehouse:
    keywords: [仓库, 货仓, 库区, 储存区, WAREHOUSE]
    confidence: 0.80
  area.truck_parking:
    keywords: [货车位, 卸货区, 货车, 装卸区, TRUCK, LOADING]
    confidence: 0.82
  area.car_parking:
    keywords: [停车位, 车位, PARKING, 停车场]
    confidence: 0.78
  area.corridor:
    keywords: [通道, 走廊, 走道, CORRIDOR, AISLE]
    confidence: 0.76
  room.control:
    keywords: [监控室, 控制室, 弱电机房, 机房]
    confidence: 0.86
```

---

## 六、semantic.json 输出格式

```json
{
  "schema_version": "1.0.0",
  "drawing_meta": {
    "source_file": "building.dxf",
    "converted_from_dwg": true,
    "extents": {
      "min": {"x": 0, "y": 0},
      "max": {"x": 60000, "y": 40000}
    },
    "unit": "mm"
  },
  "coordinate_system": {
    "unit": "mm",
    "scale_to_meters": 0.001,
    "three_js_mapping": "x→x, y→-z, elevation=0"
  },
  "devices": [
    {
      "id": "dev_0001",
      "type": "security.camera",
      "source_entity_id": "1A3F",
      "original_layer": "CCTV-DEVICE",
      "original_block_name": "DOME_CAM",
      "confidence": 0.94,
      "review_needed": false,
      "geometry": {"type": "Point", "position": {"x": 12500.0, "y": 8300.0}},
      "orientation": {"angle_deg": 135.0},
      "attributes": {"tag": "C-01"}
    }
  ],
  "cables": [
    {
      "id": "cab_0001",
      "type": "cable.network",
      "source_entity_id": "2B4C",
      "original_layer": "NET-CABLE",
      "confidence": 0.80,
      "geometry": {
        "type": "Polyline",
        "points": [
          {"x": 12500.0, "y": 8300.0},
          {"x": 12500.0, "y": 5000.0}
        ]
      }
    }
  ],
  "areas": [
    {
      "id": "area_0001",
      "type": "area.office",
      "label": "办公区A",
      "source_entity_id": "3C5D",
      "original_layer": "AREA-BOUNDARY",
      "confidence": 0.83,
      "geometry": {
        "type": "Polygon",
        "points": [
          {"x": 5000.0, "y": 5000.0},
          {"x": 25000.0, "y": 5000.0},
          {"x": 25000.0, "y": 20000.0},
          {"x": 5000.0, "y": 20000.0}
        ],
        "closed": true
      },
      "area_m2": 300.0
    }
  ],
  "parking_spaces": [],
  "annotations": []
}
```

---

## 七、前端实现规格

### 7.1 App.vue 结构

```
<template>
  <div class="app">
    <UploadZone v-if="!cadStore.hasData" />
    <div v-else class="viewer-layout">
      <LayerPanel />        <!-- 左侧：系统过滤、图层开关 -->
      <ThreeViewer />       <!-- 中央：Three.js 画布 -->
      <DevicePanel />       <!-- 右侧：点击设备后显示属性 -->
    </div>
  </div>
</template>
```

### 7.2 renderer/CoordMapper.js

```javascript
export class CoordMapper {
  constructor(extents) {
    // extents: { min: {x, y}, max: {x, y} } 单位 mm
    this.scale = 0.001  // mm → m
    this.offsetX = -(extents.min.x + extents.max.x) / 2 * this.scale
    this.offsetZ =  (extents.min.y + extents.max.y) / 2 * this.scale
  }

  toThree(cadX, cadY, elevationM = 0) {
    return {
      x: cadX * this.scale + this.offsetX,
      y: elevationM,
      z: -cadY * this.scale + this.offsetZ,
    }
  }

  pointsToVectors(points, elevation = 0) {
    return points.map(p => {
      const t = this.toThree(p.x, p.y, elevation)
      return new THREE.Vector3(t.x, t.y, t.z)
    })
  }
}
```

### 7.3 renderer/SceneBuilder.js

```javascript
import * as THREE from 'three'
import { CoordMapper } from './CoordMapper'
import { DeviceFactory } from './DeviceFactory'
import { AreaRenderer } from './AreaRenderer'
import { CableRenderer } from './CableRenderer'

export class SceneBuilder {
  constructor(scene, semantic) {
    this.scene = scene
    this.mapper = new CoordMapper(semantic.drawing_meta.extents)
    this.groups = {
      security: new THREE.Group(),
      network:  new THREE.Group(),
      cable:    new THREE.Group(),
      area:     new THREE.Group(),
      parking:  new THREE.Group(),
      annotation: new THREE.Group(),
      ground:   new THREE.Group(),
    }
    Object.entries(this.groups).forEach(([name, g]) => {
      g.name = name
      scene.add(g)
    })
    this._addGround(semantic.drawing_meta.extents)
  }

  build(semantic) {
    semantic.areas.forEach(area => {
      const mesh = AreaRenderer.buildArea(area, this.mapper)
      mesh.userData = { entityType: 'area', data: area }
      this.groups.area.add(mesh)
    })

    semantic.parking_spaces.forEach(p => {
      const mesh = AreaRenderer.buildParking(p, this.mapper)
      mesh.userData = { entityType: 'parking', data: p }
      this.groups.parking.add(mesh)
    })

    semantic.devices.forEach(dev => {
      const obj = DeviceFactory.create(dev, this.mapper)
      obj.traverse(child => { child.userData = { entityType: 'device', data: dev } })
      const category = dev.type.split('.')[0]
      ;(this.groups[category] ?? this.groups.network).add(obj)
    })

    semantic.cables.forEach(cable => {
      const line = CableRenderer.build(cable, this.mapper)
      line.userData = { entityType: 'cable', data: cable }
      this.groups.cable.add(line)
    })
  }

  setGroupVisible(groupName, visible) {
    if (this.groups[groupName]) this.groups[groupName].visible = visible
  }

  highlightObjects(ids, color = 0xff4400) {
    this.scene.traverse(obj => {
      if (ids.includes(obj.userData?.data?.id)) {
        if (obj.material) obj.material.color.setHex(color)
      }
    })
  }

  _addGround(extents) {
    const w = (extents.max.x - extents.min.x) * 0.001
    const h = (extents.max.y - extents.min.y) * 0.001
    const geo = new THREE.PlaneGeometry(w * 1.1, h * 1.1)
    const mat = new THREE.MeshBasicMaterial({ color: 0x1a1a2e, side: THREE.DoubleSide })
    const ground = new THREE.Mesh(geo, mat)
    ground.rotation.x = -Math.PI / 2
    ground.position.y = -0.01
    this.groups.ground.add(ground)
    // 网格线
    const grid = new THREE.GridHelper(Math.max(w, h) * 1.2, 20, 0x333355, 0x222244)
    this.groups.ground.add(grid)
  }
}
```

### 7.4 renderer/DeviceFactory.js

```javascript
import * as THREE from 'three'

// 颜色映射
const TYPE_COLORS = {
  'security.camera': 0xff3333,
  'security.access_control': 0xff6600,
  'network.ap': 0x3399ff,
  'network.switch': 0x0066cc,
  'network.cabinet': 0x224466,
  'network.outlet': 0x66aaff,
  'broadcast.speaker': 0xff9900,
  'alarm.detector': 0xff0000,
  'weak_electric.box': 0x888888,
}

export class DeviceFactory {
  static create(device, mapper) {
    const pos = device.geometry.position
    const t = mapper.toThree(pos.x, pos.y)
    const color = TYPE_COLORS[device.type] ?? 0xaaaaaa
    const group = new THREE.Group()
    group.position.set(t.x, 0, t.z)

    switch (device.type) {
      case 'security.camera':
        DeviceFactory._buildCamera(group, device, color)
        break
      case 'network.ap':
        DeviceFactory._buildAP(group, color)
        break
      case 'network.cabinet':
        DeviceFactory._buildCabinet(group, color)
        break
      case 'network.switch':
        DeviceFactory._buildSwitch(group, color)
        break
      default:
        DeviceFactory._buildGeneric(group, color)
    }

    if (device.orientation?.angle_deg != null) {
      group.rotation.y = -device.orientation.angle_deg * Math.PI / 180
    }

    return group
  }

  static _buildCamera(group, device, color) {
    // 机身
    const body = new THREE.Mesh(
      new THREE.CylinderGeometry(0.05, 0.07, 0.15, 12),
      new THREE.MeshPhongMaterial({ color })
    )
    body.position.y = 2.5
    group.add(body)

    // 视角锥（默认隐藏，点击显示）
    const fovRad = ((device.orientation?.fov_deg ?? 80) / 2) * Math.PI / 180
    const coneLen = 4
    const cone = new THREE.Mesh(
      new THREE.ConeGeometry(Math.tan(fovRad) * coneLen, coneLen, 16, 1, true),
      new THREE.MeshBasicMaterial({
        color: 0xff2200, transparent: true, opacity: 0.15, side: THREE.DoubleSide
      })
    )
    cone.position.y = 2.5 - coneLen / 2
    cone.rotation.x = Math.PI
    cone.visible = false
    cone.name = 'fov_cone'
    group.add(cone)
  }

  static _buildAP(group, color) {
    const mesh = new THREE.Mesh(
      new THREE.CylinderGeometry(0.15, 0.15, 0.03, 16),
      new THREE.MeshPhongMaterial({ color })
    )
    mesh.position.y = 2.8
    group.add(mesh)
  }

  static _buildCabinet(group, color) {
    const mesh = new THREE.Mesh(
      new THREE.BoxGeometry(0.6, 2.0, 0.6),
      new THREE.MeshPhongMaterial({ color })
    )
    mesh.position.y = 1.0
    group.add(mesh)
  }

  static _buildSwitch(group, color) {
    const mesh = new THREE.Mesh(
      new THREE.BoxGeometry(0.44, 0.05, 0.28),
      new THREE.MeshPhongMaterial({ color })
    )
    mesh.position.y = 1.5
    group.add(mesh)
  }

  static _buildGeneric(group, color) {
    const mesh = new THREE.Mesh(
      new THREE.BoxGeometry(0.2, 0.2, 0.2),
      new THREE.MeshPhongMaterial({ color })
    )
    mesh.position.y = 0.1
    group.add(mesh)
  }
}
```

### 7.5 renderer/AreaRenderer.js

```javascript
import * as THREE from 'three'

const AREA_COLORS = {
  'area.office':     { fill: 0x4488ff, opacity: 0.18 },
  'area.warehouse':  { fill: 0xffaa22, opacity: 0.18 },
  'area.truck_parking': { fill: 0xff6622, opacity: 0.22 },
  'area.car_parking':   { fill: 0xffee22, opacity: 0.22 },
  'area.corridor':   { fill: 0x88ff88, opacity: 0.15 },
  'parking.truck':   { fill: 0xff6622, opacity: 0.25 },
}

export class AreaRenderer {
  static buildArea(area, mapper) {
    const pts = mapper.pointsToVectors(area.geometry.points, 0)
    return AreaRenderer._buildShape(pts, AREA_COLORS[area.type] ?? { fill: 0xffffff, opacity: 0.1 })
  }

  static buildParking(parking, mapper) {
    const pts = mapper.pointsToVectors(parking.geometry.points, 0)
    return AreaRenderer._buildShape(pts, AREA_COLORS[parking.type] ?? { fill: 0xffee22, opacity: 0.25 })
  }

  static _buildShape(vectors, style) {
    const shape = new THREE.Shape()
    if (vectors.length < 3) return new THREE.Group()
    shape.moveTo(vectors[0].x, vectors[0].z)
    vectors.slice(1).forEach(v => shape.lineTo(v.x, v.z))
    shape.closePath()

    const geo = new THREE.ShapeGeometry(shape)
    const mat = new THREE.MeshBasicMaterial({
      color: style.fill,
      transparent: true,
      opacity: style.opacity,
      side: THREE.DoubleSide,
    })
    const mesh = new THREE.Mesh(geo, mat)
    mesh.rotation.x = -Math.PI / 2
    mesh.position.y = 0.01

    // 轮廓线
    const edgeMat = new THREE.LineBasicMaterial({ color: style.fill, opacity: 0.6, transparent: true })
    const edgePts = [...vectors, vectors[0]]
    const edgeGeo = new THREE.BufferGeometry().setFromPoints(edgePts)
    const edge = new THREE.Line(edgeGeo, edgeMat)

    const group = new THREE.Group()
    group.add(mesh)
    group.add(edge)
    return group
  }
}
```

### 7.6 renderer/CableRenderer.js

```javascript
import * as THREE from 'three'

const CABLE_COLORS = {
  'cable.network': 0x44aaff,
  'cable.fiber':   0xff44ff,
  'cable.trunk':   0xaaaaaa,
  'cable.power':   0xff4444,
}

export class CableRenderer {
  static build(cable, mapper) {
    const pts = mapper.pointsToVectors(cable.geometry.points, 0.05)
    const color = CABLE_COLORS[cable.type] ?? 0x888888
    const geo = new THREE.BufferGeometry().setFromPoints(pts)
    const mat = new THREE.LineBasicMaterial({ color, linewidth: 1 })
    return new THREE.Line(geo, mat)
  }
}
```

### 7.7 ThreeViewer.vue（核心片段）

```javascript
// setup() 中
onMounted(() => {
  // 场景初始化
  scene = new THREE.Scene()
  scene.background = new THREE.Color(0x0d0d1a)
  camera = new THREE.PerspectiveCamera(45, canvas.clientWidth / canvas.clientHeight, 0.1, 5000)
  camera.position.set(0, 80, 80)
  camera.lookAt(0, 0, 0)
  renderer = new THREE.WebGLRenderer({ canvas, antialias: true })
  renderer.setPixelRatio(window.devicePixelRatio)

  // 灯光
  scene.add(new THREE.AmbientLight(0xffffff, 0.6))
  const dirLight = new THREE.DirectionalLight(0xffffff, 0.8)
  dirLight.position.set(50, 100, 50)
  scene.add(dirLight)

  // OrbitControls
  controls = new OrbitControls(camera, renderer.domElement)
  controls.enableDamping = true
  controls.dampingFactor = 0.05

  // 点击拾取
  renderer.domElement.addEventListener('click', onCanvasClick)

  animate()
})

// 监听 semantic 数据变化
watch(() => cadStore.semantic, (semantic) => {
  if (!semantic) return
  // 清空旧场景
  while (scene.children.length > 0) scene.remove(scene.children[0])
  builder = new SceneBuilder(scene, semantic)
  builder.build(semantic)
})

// 点击设备
function onCanvasClick(e) {
  const rect = renderer.domElement.getBoundingClientRect()
  mouse.x = ((e.clientX - rect.left) / rect.width) * 2 - 1
  mouse.y = -((e.clientY - rect.top) / rect.height) * 2 + 1
  raycaster.setFromCamera(mouse, camera)
  const hits = raycaster.intersectObjects(scene.children, true)
  if (hits.length === 0) { cadStore.selectedDevice = null; return }

  // 向上找到有 userData 的父对象
  let obj = hits[0].object
  while (obj && !obj.userData?.entityType) obj = obj.parent
  if (!obj) return

  if (obj.userData.entityType === 'device') {
    cadStore.selectedDevice = obj.userData.data
    // 摄像头：显示/隐藏视角锥
    obj.traverse(child => {
      if (child.name === 'fov_cone') child.visible = !child.visible
    })
  }
}
```

### 7.8 LayerPanel.vue（系统过滤）

```vue
<template>
  <aside class="layer-panel">
    <h3>系统过滤</h3>
    <label v-for="sys in systems" :key="sys.key">
      <input type="checkbox" v-model="sys.visible"
        @change="toggleSystem(sys.key, sys.visible)" />
      <span :style="{ color: sys.color }">{{ sys.label }}</span>
    </label>
  </aside>
</template>

<script setup>
const systems = ref([
  { key: 'security', label: '监控系统', color: '#ff3333', visible: true },
  { key: 'network',  label: '网络系统', color: '#3399ff', visible: true },
  { key: 'cable',    label: '线路',     color: '#44aaff', visible: true },
  { key: 'area',     label: '区域',     color: '#88ff88', visible: true },
  { key: 'parking',  label: '车位',     color: '#ffee22', visible: true },
])

function toggleSystem(key, visible) {
  cadStore.sceneBuilder?.setGroupVisible(key, visible)
}
</script>
```

---

## 八、Pinia Store (stores/cad.js)

```javascript
import { defineStore } from 'pinia'

export const useCadStore = defineStore('cad', {
  state: () => ({
    fileId: null,
    semantic: null,
    selectedDevice: null,
    sceneBuilder: null,   // SceneBuilder 实例引用
    loading: false,
    error: null,
  }),
  actions: {
    async uploadFile(file) {
      this.loading = true
      const form = new FormData()
      form.append('file', file)
      const res = await fetch('http://localhost:8000/api/upload', { method: 'POST', body: form })
      const data = await res.json()
      this.fileId = data.file_id
    },
    async parseFile() {
      this.loading = true
      const res = await fetch('http://localhost:8000/api/parse', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ file_id: this.fileId }),
      })
      this.semantic = await res.json()
      this.loading = false
    },
  },
})
```

---

## 九、package.json（前端）

```json
{
  "name": "cad-preview",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "vue": "^3.4.0",
    "pinia": "^2.1.0",
    "three": "^0.167.0",
    "axios": "^1.7.0"
  },
  "devDependencies": {
    "@vitejs/plugin-vue": "^5.0.0",
    "vite": "^5.0.0"
  }
}
```

---

## 十、开发阶段（Codex 执行顺序）

### 阶段 1：后端搭建（先做）

**目标：** 能上传 DXF 并返回 semantic.json

1. 创建 `backend/` 目录结构
2. 实现 `requirements.txt` 并安装依赖
3. 实现 `main.py`（FastAPI，CORS）
4. 实现 `api/upload.py`（接收文件，存储，检测格式）
5. 实现 `parser/dwg_converter.py`（ODA FC 调用）
6. 实现 `parser/dxf_reader.py`（ezdxf 遍历实体）
7. 实现 `semantic/rule_engine.py`（mapping.yaml 匹配）
8. 实现 `semantic/geometry_utils.py`（闭合多边形、文字关联）
9. 实现 `config/mapping.yaml`（完整规则）
10. 实现 `api/parse.py`（组装 semantic.json）
11. **验证：** `curl -F "file=@test.dxf" http://localhost:8000/api/upload` 返回 file_id；`POST /api/parse` 返回 semantic.json

### 阶段 2：前端搭建（阶段1完成后）

1. 创建 `frontend/` Vue 3 + Vite 项目
2. 实现 `stores/cad.js`（Pinia）
3. 实现 `renderer/CoordMapper.js`
4. 实现 `renderer/AreaRenderer.js`
5. 实现 `renderer/CableRenderer.js`
6. 实现 `renderer/DeviceFactory.js`
7. 实现 `renderer/SceneBuilder.js`
8. 实现 `components/UploadZone.vue`
9. 实现 `components/ThreeViewer.vue`（含点击拾取）
10. 实现 `components/LayerPanel.vue`（系统过滤）
11. 实现 `components/DevicePanel.vue`（属性显示）
12. 实现 `App.vue`（整体布局）
13. **验证：** 上传 DXF 后在 Three.js 中能看到设备、线路、区域；点击设备有属性弹窗；过滤 checkbox 能切换显示/隐藏

### 阶段 3：DWG 兼容（最后做）

1. 确认 ODA File Converter 已安装
2. 测试 `dwg_converter.py` 转换真实 DWG 文件
3. 调整 ODA FC 路径配置（支持环境变量 `ODA_FC_PATH`）
4. **验证：** 上传 `.dwg` 文件完整走通全流程

---

## 十一、ODA File Converter 安装说明

**下载地址：** https://www.opendesign.com/guestfiles/oda_file_converter

**Windows 安装后路径：**
```
C:\Program Files\ODA\ODAFileConverter\ODAFileConverter.exe
```

**Linux 安装：**
```bash
sudo dpkg -i oda_file_converter_*.deb
# 或
sudo rpm -i oda_file_converter_*.rpm
```

**通过环境变量配置路径（推荐）：**
在 `dwg_converter.py` 中优先读取：
```python
import os
oda_path = os.environ.get("ODA_FC_PATH") or cls.find_oda()
```

---

## 十二、验证检查清单

- [ ] `POST /api/upload` 上传 DXF，返回 `file_id`
- [ ] `POST /api/parse` 返回完整 semantic.json，含 devices/cables/areas
- [ ] 前端能拖拽上传文件
- [ ] Three.js 场景渲染出设备（摄像头、AP、机柜）
- [ ] Three.js 场景渲染出线路（不同颜色）
- [ ] Three.js 场景渲染出区域（半透明面片）
- [ ] 点击设备弹出属性面板（显示 type、layer、block_name、confidence）
- [ ] 点击摄像头显示/隐藏视角锥
- [ ] 左侧过滤 checkbox 控制各系统显示/隐藏
- [ ] 上传 DWG 文件自动转换后走通全流程（阶段3）

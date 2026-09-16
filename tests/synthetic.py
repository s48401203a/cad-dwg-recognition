"""合成 DXF 夹具。

全部由代码生成，**不含任何客户图纸数据**。用行为命名，覆盖：
基本强弱电、空图、不同单位、无单位、弧形与闭合多段线、块变换（旋转/镜像/
非均匀缩放/嵌套）、重复图例、未知块、畸形输入。

约定：`build_*()` 返回一个 ezdxf 文档；`write_dxf(path, builder_result)` 落盘。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import ezdxf

# 与 tests/eval/cases.yaml 的通用最小图保持一致的图层与块名，避免出现客户专用关键词。
LAYERS = {
    "墙": 8,
    "监控": 1,
    "网络": 4,
    "弱电柜": 6,
    "桥架": 2,
    "照明": 30,
    "配电": 5,
    "强电桥架": 3,
    "标注": 7,
}


def _new_doc(units: int = 4) -> ezdxf.document.Drawing:
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = units
    for name, color in LAYERS.items():
        if name not in doc.layers:
            doc.layers.add(name, color=color)
    for block_name in ("摄像头", "无线AP", "机柜", "配电箱", "筒灯"):
        if block_name not in doc.blocks:
            block = doc.blocks.new(name=block_name)
            block.add_circle((0, 0), 200)
    return doc


def build_basic_fixture(units: int = 4) -> ezdxf.document.Drawing:
    """基本强弱电：1 面墙 + 摄像头/AP/机柜/配电箱/筒灯 + 2 条线路。"""
    doc = _new_doc(units)
    msp = doc.modelspace()
    msp.add_lwpolyline(
        [(0, 0), (20000, 0), (20000, 15000), (0, 15000)],
        close=True,
        dxfattribs={"layer": "墙"},
    )
    msp.add_blockref("摄像头", (5000, 4000), dxfattribs={"layer": "监控"})
    msp.add_text("摄像头-01", dxfattribs={"layer": "标注", "height": 250}).set_placement((5000, 4300))
    msp.add_blockref("无线AP", (15000, 4000), dxfattribs={"layer": "网络"})
    msp.add_text("AP-01", dxfattribs={"layer": "标注", "height": 250}).set_placement((15000, 4300))
    msp.add_blockref("机柜", (2500, 2000), dxfattribs={"layer": "弱电柜"})
    msp.add_text("机柜", dxfattribs={"layer": "标注", "height": 250}).set_placement((2500, 2300))
    msp.add_line((2500, 2000), (15000, 4000), dxfattribs={"layer": "桥架"})
    msp.add_blockref("筒灯", (10000, 9000), dxfattribs={"layer": "照明"})
    msp.add_text("照明", dxfattribs={"layer": "标注", "height": 250}).set_placement((10000, 9300))
    msp.add_blockref("配电箱", (18000, 2000), dxfattribs={"layer": "配电"})
    msp.add_text("配电箱", dxfattribs={"layer": "标注", "height": 250}).set_placement((18000, 2300))
    msp.add_line((18000, 2000), (10000, 9000), dxfattribs={"layer": "强电桥架"})
    return doc


def build_empty_fixture() -> ezdxf.document.Drawing:
    """空图：只有图层，没有实体。"""
    return _new_doc(4)


def build_units_fixture(units: int) -> ezdxf.document.Drawing:
    """单一 10 单位长直线，用于单位换算断言。"""
    doc = _new_doc(units)
    doc.modelspace().add_line((0, 0), (10, 0), dxfattribs={"layer": "桥架"})
    return doc


def build_bulge_fixture() -> ezdxf.document.Drawing:
    """含凸度（弧段）与闭合多段线。

    - `arc_polyline`：弦长 10、bulge=1 的半圆，弧长应为 5π。
    - `closed_rect`：闭合矩形 20x15，周长应为 70（含闭合边）。
    - `mixed`：直线 + 半圆组合，总数便于断言。
    """
    doc = _new_doc(4)
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0, 1.0), (10, 0, 0.0)], format="xyb", dxfattribs={"layer": "桥架"})
    msp.add_lwpolyline(
        [(100, 0), (120, 0), (120, 15), (100, 15)],
        close=True,
        dxfattribs={"layer": "墙"},
    )
    msp.add_lwpolyline(
        [(200, 0, 1.0), (210, 0, 0.0), (220, 0, 1.0), (230, 0, 0.0)],
        format="xyb",
        dxfattribs={"layer": "桥架"},
    )
    msp.add_arc((300, 0), 10, 0, 270, dxfattribs={"layer": "桥架"})
    return doc


def build_block_transform_fixture() -> ezdxf.document.Drawing:
    """块引用变换矩阵：旋转、镜像（负缩放）、非均匀缩放、嵌套块。

    每个块内的可见几何都是一个以原点为中心、边长为 2 的正方形（角点在
    (±1, ±1)），因此可以通过 `cad_virtual_shapes` 直接验证变换结果。
    """
    doc = _new_doc(4)
    square = doc.blocks.new(name="方块")
    square.add_lwpolyline([(-1, -1), (1, -1), (1, 1), (-1, 1)], close=True)

    inner = doc.blocks.new(name="内块")
    inner.add_blockref("方块", (0, 0))

    nested = doc.blocks.new(name="嵌套块")
    nested.add_blockref("内块", (0, 0))

    msp = doc.modelspace()
    # 旋转 90°：正方形变换后仍占同样包围盒，但顶点顺序变化
    msp.add_blockref("方块", (1000, 0), dxfattribs={"layer": "墙", "rotation": 90})
    # 镜向（x 负缩放）
    msp.add_blockref("方块", (2000, 0), dxfattribs={"layer": "墙", "xscale": -1})
    # 非均匀缩放 3x1
    msp.add_blockref("方块", (3000, 0), dxfattribs={"layer": "墙", "xscale": 3, "yscale": 1})
    # 嵌套两层
    msp.add_blockref("嵌套块", (4000, 0), dxfattribs={"layer": "墙"})
    return doc


def build_duplicate_legend_fixture() -> ezdxf.document.Drawing:
    """重复图例：同一设备既有块符号又有文字标注，且重复两次。"""
    doc = _new_doc(4)
    msp = doc.modelspace()
    for index, x in enumerate((1000.0, 3000.0), start=1):
        msp.add_blockref("摄像头", (x, 1000), dxfattribs={"layer": "监控"})
        msp.add_text(f"摄像头-{index:02d}", dxfattribs={"layer": "标注", "height": 250}).set_placement((x, 1300))
    return doc


def build_unknown_block_fixture() -> ezdxf.document.Drawing:
    """未知块：名称不在任何规则内，且没有文字标注。"""
    doc = _new_doc(4)
    block = doc.blocks.new(name="ZZZ_UNKNOWN_9999")
    block.add_circle((0, 0), 150)
    doc.modelspace().add_blockref("ZZZ_UNKNOWN_9999", (5000, 5000), dxfattribs={"layer": "0"})
    return doc


def build_malformed_text() -> str:
    """畸形 DXF 文本：截断的 group code 流。"""
    return "0\nSECTION\n2\nHEADER\n9\n$INSUNITS\n70\n4\n0\nENDSEC\n0\nSECTION\n2\nENTITIES\n0\nLINE\n8\n墙\n10\n"


def build_unsupported_entity_fixture() -> ezdxf.document.Drawing:
    """包含读取器不支持的实体类型（SPLINE/POINT），用于验证跳过而非崩溃。"""
    doc = _new_doc(4)
    msp = doc.modelspace()
    msp.add_spline([(0, 0), (10, 10), (20, 0)])
    msp.add_point((5, 5))
    msp.add_line((0, 0), (100, 0), dxfattribs={"layer": "桥架"})
    return doc


def build_unit_scale_line_fixture(units: int) -> ezdxf.document.Drawing:
    """单位换算用：在原点放一条长度恰好 1 个图纸单位的直线。

    与 `build_units_fixture`（固定 10 单位）互补：这里长度是 1，坐标乘上
    单位毫米比例之后应当等于「同一物理长度」，便于跨单位往返比对。
    """
    doc = _new_doc(units)
    doc.modelspace().add_line((0, 0), (1, 0), dxfattribs={"layer": "桥架"})
    return doc


def _role_block_doc(x: float, rotation: float) -> ezdxf.document.Drawing:
    """共用的角色块图纸：块名含「摄像头」，命中 `_insert_cad_role` 的 camera_symbol。

    块内几何是以原点为中心、边长 2 的正方形（角点 (±1, ±1)）加一段半径 0.5 的
    90° 圆弧，因此可以直接验证块变换后的坐标与弧长。
    """
    doc = _new_doc(4)
    block = doc.blocks.new(name="摄像头-方块")
    block.add_lwpolyline([(-1, -1), (1, -1), (1, 1), (-1, 1)], close=True)
    block.add_arc((0, 0), 0.5, 0, 90)
    doc.modelspace().add_blockref("摄像头-方块", (x, 0), dxfattribs={"layer": "监控", "rotation": rotation})
    return doc


def build_role_block_fixture() -> ezdxf.document.Drawing:
    """块名命中 CAD 角色（摄像头）的块引用，旋转 90°，用于验证 `cad_virtual_shapes`。

    `build_block_transform_fixture()` 的块名（方块/内块/嵌套块）都不匹配角色关键词，
    因此拿不到虚拟几何；这一份专门让角色匹配路径也被覆盖。
    """
    return _role_block_doc(1000.0, 90.0)


def build_role_block_unrotated_fixture() -> ezdxf.document.Drawing:
    """同上但不旋转：虚拟几何坐标应等于「块内坐标 + 插入点」。"""
    return _role_block_doc(0.0, 0.0)


def build_nested_role_block_fixture() -> ezdxf.document.Drawing:
    """两层嵌套：外层块名命中角色，内层块再引用真正的摄像头块。

    ezdxf 的 `virtual_entities()` 只展开一层，因此这里用于验证「嵌套块里的
    虚拟几何是否被读取器展开」这一限制。
    """
    doc = _new_doc(4)
    block = doc.blocks.new(name="摄像头-方块")
    block.add_lwpolyline([(-1, -1), (1, -1), (1, 1), (-1, 1)], close=True)
    inner = doc.blocks.new(name="内层摄像头")
    inner.add_blockref("摄像头-方块", (0, 0))
    doc.modelspace().add_blockref("内层摄像头", (5000, 0), dxfattribs={"layer": "监控"})
    return doc


BUILDERS: dict[str, Callable[[], ezdxf.document.Drawing]] = {
    "basic": build_basic_fixture,
    "empty": build_empty_fixture,
    "bulge": build_bulge_fixture,
    "block_transform": build_block_transform_fixture,
    "duplicate_legend": build_duplicate_legend_fixture,
    "unknown_block": build_unknown_block_fixture,
    "unsupported_entity": build_unsupported_entity_fixture,
    "unit_scale_line": build_unit_scale_line_fixture,
    "role_block": build_role_block_fixture,
    "role_block_unrotated": build_role_block_unrotated_fixture,
    "nested_role_block": build_nested_role_block_fixture,
}


def build_named(name: str, **kwargs: Any) -> ezdxf.document.Drawing:
    builder = BUILDERS.get(name)
    if builder is None:
        raise KeyError(f"未知夹具名称: {name}（可用: {', '.join(sorted(BUILDERS))}）")
    return builder(**kwargs)  # type: ignore[misc]


def write_dxf(path: Path, doc: ezdxf.document.Drawing) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(path)
    return path


def build_and_write(name: str, path: Path, **kwargs: Any) -> Path:
    return write_dxf(path, build_named(name, **kwargs))

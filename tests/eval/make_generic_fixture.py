from __future__ import annotations

from pathlib import Path

import ezdxf


ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "generic_electrical_min.dxf"


def build_generic_electrical_min(path: Path = FIXTURE_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 4
    layers = {
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
    for name, color in layers.items():
        if name not in doc.layers:
            doc.layers.add(name, color=color)

    for block_name in ("摄像头", "无线AP", "机柜", "配电箱", "筒灯"):
        if block_name not in doc.blocks:
            block = doc.blocks.new(name=block_name)
            block.add_circle((0, 0), 200)

    msp = doc.modelspace()
    msp.add_lwpolyline(
        [(0, 0), (20000, 0), (20000, 15000), (0, 15000), (0, 0)],
        close=True,
        dxfattribs={"layer": "墙"},
    )
    msp.add_blockref("摄像头", (5000, 4000), dxfattribs={"layer": "监控"})
    msp.add_text("摄像头-01", dxfattribs={"layer": "标注", "height": 250}).set_placement((5000, 4300))
    msp.add_blockref("无线AP", (15000, 4000), dxfattribs={"layer": "网络"})
    msp.add_text("AP-01", dxfattribs={"layer": "标注", "height": 250}).set_placement((15000, 4300))
    msp.add_blockref("机柜", (2500, 2000), dxfattribs={"layer": "弱电柜"})
    msp.add_text("机柜", dxfattribs={"layer": "标注", "height": 250}).set_placement((2500, 2300))
    msp.add_lwpolyline(
        [(2300, 1800), (2700, 1800), (2700, 2200), (2300, 2200), (2300, 1800)],
        close=True,
        dxfattribs={"layer": "弱电柜"},
    )
    msp.add_line((2500, 2000), (15000, 4000), dxfattribs={"layer": "桥架"})
    msp.add_blockref("筒灯", (10000, 9000), dxfattribs={"layer": "照明"})
    msp.add_text("照明", dxfattribs={"layer": "标注", "height": 250}).set_placement((10000, 9300))
    msp.add_blockref("配电箱", (18000, 2000), dxfattribs={"layer": "配电"})
    msp.add_text("配电箱", dxfattribs={"layer": "标注", "height": 250}).set_placement((18000, 2300))
    msp.add_line((18000, 2000), (10000, 9000), dxfattribs={"layer": "强电桥架"})
    doc.saveas(path)
    return path


if __name__ == "__main__":
    # 默认**不**写回被跟踪的夹具文件：直接运行脚本不应修改工作区。
    # 需要落到磁盘时显式给出路径，例如：
    #   python -m tests.eval.make_generic_fixture /tmp/sample.dxf      （写到指定路径）
    #   python -m tests.eval.make_generic_fixture --tracked           （确认后才覆盖仓库夹具，仅供维护者）
    import sys

    args = [item for item in sys.argv[1:]]
    if "--tracked" in args:
        target = FIXTURE_PATH
    elif args:
        target = Path(args[0]).expanduser()
    else:
        import tempfile

        target = Path(tempfile.mkdtemp(prefix="cad-sample-")) / "generic_electrical_min.dxf"
    path = build_generic_electrical_min(target)
    print(path)
    if path == FIXTURE_PATH:
        print("注意：已覆盖仓库内被跟踪的夹具，请检查 git diff 后再提交。")

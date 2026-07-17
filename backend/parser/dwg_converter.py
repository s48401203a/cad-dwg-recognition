import subprocess
import os
from pathlib import Path
from typing import Callable


def _resolve_converter_binary(path: Path) -> Path | None:
    if path.is_file():
        return path
    if path.suffix.lower() == ".app":
        mac_binary = path / "Contents" / "MacOS" / "ODAFileConverter"
        if mac_binary.exists():
            return mac_binary
    return None


def find_oda_file_converter() -> Path | None:
    env_path = os.environ.get("ODA_FILE_CONVERTER")
    if env_path:
        candidate = _resolve_converter_binary(Path(env_path))
        if candidate:
            return candidate

    roots = [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "ODA",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "ODA",
    ]
    matches: list[Path] = []
    for root in roots:
        if root.exists():
            matches.extend(root.glob("ODAFileConverter*/ODAFileConverter.exe"))
    if matches:
        return sorted(matches, key=lambda path: path.parent.name, reverse=True)[0]

    mac_candidates = [
        Path("/Applications/ODAFileConverter.app"),
        Path("/Applications/ODAFileConverter.app/Contents/MacOS/ODAFileConverter"),
    ]
    for path in mac_candidates:
        candidate = _resolve_converter_binary(path)
        if candidate:
            return candidate
    return None


class DwgConverter:
    @staticmethod
    def available() -> bool:
        return find_oda_file_converter() is not None

    @staticmethod
    def convert(dwg_path: Path, output_dir: Path, log_callback: Callable[[str], None] | None = None) -> Path:
        if not dwg_path.exists():
            raise FileNotFoundError(f"DWG 文件不存在: {dwg_path}")
        if dwg_path.suffix.lower() != ".dwg":
            raise ValueError(f"不是 DWG 文件: {dwg_path.name}")
        oda_path = find_oda_file_converter()
        if not oda_path:
            raise FileNotFoundError("未找到 ODA File Converter，请安装后重试，或设置 ODA_FILE_CONVERTER 环境变量。")

        output_dir.mkdir(parents=True, exist_ok=True)
        command = [
            str(oda_path),
            str(dwg_path.parent),
            str(output_dir),
            "ACAD2018",
            "DXF",
            "0",
            "1",
            dwg_path.name,
        ]
        if log_callback:
            log_callback("调用 ODA File Converter 转换 DWG -> DXF...")
        result = subprocess.run(command, capture_output=True, text=True, timeout=120)
        candidates = sorted(output_dir.glob(f"{dwg_path.stem}*.dxf"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not candidates:
            candidates = sorted(output_dir.rglob("*.dxf"), key=lambda p: p.stat().st_mtime, reverse=True)
        if result.returncode != 0 or not candidates:
            details = (result.stderr or result.stdout or "ODA 未输出错误详情").strip()
            raise RuntimeError(f"DWG 转 DXF 失败: {details}")
        converted = candidates[0]
        if log_callback:
            log_callback(f"DWG 转换完成: {converted.name}")
        return converted

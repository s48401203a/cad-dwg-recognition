# CAD Warehouse 3D Viewer

本项目用于在本地 Web 页面中上传 DWG/DXF 图纸，解析弱电设备、线路、建筑边界、车位/月台等对象，并生成 Three.js 3D 预览。

![脱敏演示图](docs/assets/demo-sanitized.png)

## 隐私说明

仓库只保存源代码和脱敏演示图，不保存真实客户图纸、解析 JSON、生成结果目录、日志或本机运行状态。

以下目录默认被 `.gitignore` 排除：

- `backend/uploads/`
- `backend/projects/`
- `backend/logs/`
- `backups/`
- `exports/`
- `反推项目/`
- `.codex-tmp/`
- `.runtime-macos/`
- `.venv-macos/`
- `PROGRESS.md`
- `操作手册.md`
- `启动说明.md`

真实图纸和解析后的项目数据只应保存在本机或内部受控存储中，不应提交到 Git。

## 启动

双击：

```text
启动项目.bat
```

或在 PowerShell 中运行：

```powershell
.\start-project.ps1
```

默认访问地址：

```text
http://127.0.0.1:8000
```

## 换电脑 / U 盘迁移

可以把项目目录复制到另一台 Windows 电脑，但新电脑需要准备运行环境。建议复制源码目录，不要依赖旧电脑里的 `.venv`。

在新电脑上先双击：

```text
安装环境.bat
```

脚本会创建本项目专用 `.venv`，安装 Python 依赖，并检测 ODA File Converter。完成后再双击：

```text
启动项目.bat
```

如果新电脑没有 Python，脚本会优先尝试通过 `winget` 安装 Python 3.12。DWG 文件解析需要 ODA File Converter；如果无法自动安装，请手动安装 ODA File Converter 后重新运行安装脚本。DXF 文件不需要 ODA 转换。

如果新电脑不能联网，可以先在有网电脑上下载 Python 依赖包：

```powershell
python -m pip download -r requirements.txt -d wheelhouse
```

然后把 `wheelhouse/` 一起复制到新电脑。`安装环境.bat` 会自动优先使用这个本地依赖目录。

## 使用流程

1. 打开本地 Web 页面。
2. 上传 DWG 或 DXF。
3. 点击解析并生成 3D。
4. 使用图层开关、视角按钮和对象信息面板查看模型。

## 依赖

- Python 3.10+
- FastAPI
- Uvicorn
- ezdxf
- PyYAML
- ODA File Converter，用于 DWG 转 DXF

安装 Python 依赖：

```powershell
pip install -r requirements.txt
```

## GitHub 发布要求

发布到 GitHub 时必须创建 Private 仓库。提交前检查 GitHub Desktop 的 Changes 列表，确认没有 `.dwg`、`.dxf`、`semantic.json`、`backend/uploads/`、`backend/projects/`、真实项目截图、客户名称或本机项目路径。

# CAD 强弱电 3D 读取器

通用开源 CAD 强弱电读取与 3D 预览工具。上传 DWG/DXF 后，按图层、块名、文字识别墙体、桥架、摄像头、AP、机柜、配电、照明等对象，并生成 Three.js 3D 场景。

本仓库服务的是**通用强弱电图纸**，不是只服务某一客户。弱电与强电走同一条读取链路。默认场地包是 `generic`。百世快运 `express`、供应链 `supply_chain` 是可选场地包，需要月台、车尾、炮楼等场地推断时再启用。

![脱敏演示图](docs/assets/demo-sanitized.png)

评测说明见 [`docs/generic-cad-eval.html`](docs/generic-cad-eval.html)（可用 `file://` 打开）。

## 启动

macOS / Linux：

```bash
./start.sh
```

默认打开 Vite 预览：`http://127.0.0.1:5173`。脚本同时拉起 FastAPI 后端（默认 `http://127.0.0.1:8000`）。停止：`./stop.sh`。

Windows：

```powershell
.\start-project.ps1
```

或双击 `启动项目.bat`。Windows 默认由后端直接提供页面：`http://127.0.0.1:8000`。停止：`.\stop-project.ps1`。

健康检查：`GET /api/health`。

## 默认 profile

| Profile | 作用 |
|---|---|
| `generic` | **默认**。只按图层 / 块 / 文字读墙、桥架、摄像头、AP、机柜、配电、照明；不启用月台、车尾、炮楼推断。 |
| `express` | 可选快运场地包。月台、车尾摄像头、射灯、鱼眼 / 半球等。 |
| `supply_chain` | 可选仓储供应链场地包。货架 / 工位 / 分拣 / DWS 按场地规则渐进启用。 |

解析请求携带 `site_profiles`。不传或只传 `generic` 时走通用读取。评测夹具默认也用 `generic`。

启用可选场地包示例：

```json
{ "file_id": "<upload_id>", "site_profiles": ["express"] }
```

混合场地可传 `["express", "supply_chain"]`。可用 `GET /api/site-profiles` 查看登记列表。

## 使用流程

1. 启动后打开本地页面。
2. 上传 DWG 或 DXF。
3. 解析默认走 `generic`。需要场地推断时再启用 `express` / `supply_chain`。
4. 解析。后端将 DWG 转为 DXF（需 ODA File Converter），用 ezdxf 读实体，再由规则引擎生成语义结果。
5. 前端 Three.js 自动生成 3D。用图层开关、视角和对象信息面板查看。

纯 DXF 不需要 ODA。

## 评测

公开夹具（合成图，无客户数据）：

```bash
python tests/eval/runner.py
```

只跑公开夹具：

```bash
python tests/eval/runner.py --fixtures-only
```

通用目标严格模式（配电 / 照明 / 墙的 desired 缺口也视为失败）：

```bash
python tests/eval/runner.py --strict
```

夹具默认 profile 为 `generic`。可用 `--profile express` 覆盖。报告写到 `exports/eval/`（该目录不入库）。缺口含义见评测页。

回归计数（需要本机已有解析结果）：

```bash
python tests/regression_counts.py
```

## 隐私

以下内容**永不入库**：

- 客户 `*.dwg` / `*.dxf`（公开合成夹具 `tests/fixtures/**/*.dxf` 除外）
- `semantic.json` 与解析结果
- 客户项目目录（`backend/projects/`、`backend/uploads/`、`projects/` 等）
- 日志、备份、评测导出、本机运行状态

仓库只保留源代码和脱敏演示图 `docs/assets/demo-sanitized.png`。真实图纸只放本机或内部受控存储。

## 依赖

- Python 3.10+
- FastAPI / Uvicorn / ezdxf / PyYAML
- ODA File Converter（仅 DWG → DXF）
- macOS Vite 预览另需 Node.js（`npm install` 后由 `./start.sh` 拉起）

Windows 安装：

```powershell
.\install-env.ps1
```

可加 `-SkipOda` 跳过 ODA 检测（只测 DXF）。离线可先 `pip download -r requirements.txt -d wheelhouse`，再把 `wheelhouse/` 一并拷走。

通用安装：

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## GitHub 发布

发布到 GitHub 时必须创建 **Private** 仓库。提交前检查 Changes：不能出现客户图纸、`semantic.json`、项目目录、真实截图、客户名称或本机绝对路径。详见 `GITHUB_PUBLISH_CHECKLIST.md`。

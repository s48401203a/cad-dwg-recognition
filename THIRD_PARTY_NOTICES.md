# 第三方组件与声明

本文件列出随本仓库分发的第三方代码与素材，以及**必须随再分发保留**的声明。
本仓库**自身**的整体许可证尚未确定（见 `RELEASE_READINESS.md`）；
**任何整体许可证都不会改变下列第三方内容各自的许可条件**。

核对时间：2026-09-16（CST）。

---

## 1. 随仓库分发的第三方代码

### Three.js（r164）

| 项 | 内容 |
|---|---|
| 文件 | `frontend/vendor/three/three.module.js`（核心库）<br>`frontend/vendor/three/examples/jsm/controls/OrbitControls.js`<br>`frontend/vendor/three/examples/jsm/renderers/CSS2DRenderer.js` |
| 版本 | `const REVISION = '164'`（文件内可核） |
| 许可 | MIT |
| 著作权 | `Copyright © 2010-2024 three.js authors` |
| 上游 | <https://github.com/mrdoob/three.js>（r164 标签） |
| 许可全文 | 官方全文见 <https://raw.githubusercontent.com/mrdoob/three.js/r164/LICENSE>；本仓库已随文件附带副本：`frontend/vendor/three/LICENSE` |
| 是否修改 | **未修改**。三个文件均为上游原样拷贝 |

**本轮补齐的声明（此前不完整）**：`three.module.js` 原本只有 `@license` 与
`SPDX-License-Identifier: MIT` 与版权行，**缺少 MIT 要求的完整许可声明文本**；
两个 `examples/jsm/**` 文件**完全没有版权与许可声明**。MIT 的条件是
"The above copyright notice and this permission notice shall be included in all copies or
substantial portions of the Software"，因此已补充 `frontend/vendor/three/LICENSE`
（上游原文），使再分发满足该条件。

> 说明：SPDX 标识是**机器可读的许可标识**，本身**不构成**许可义务的履行；
> 版权声明 + 许可声明文本才是 MIT 明文要求的内容。

## 2. 仅作为依赖声明、未内嵌代码的第三方组件

这些组件通过包管理器安装，**仓库中不含其源码**，因此不随本仓库再分发；
使用者安装时适用各自的许可证。清单用于透明化依赖关系，不构成对其许可的声明。

| 组件 | 用途 | 出现在 |
|---|---|---|
| FastAPI、Uvicorn、Starlette、Pydantic、anyio、python-multipart、websockets、httptools 等 | HTTP/WebSocket 服务 | `requirements.txt` |
| ezdxf | DXF 读取 | `requirements.txt` |
| PyYAML | 规则与配置解析 | `requirements.txt` |
| aiofiles | 上传流式写入 | `requirements.txt` |
| matplotlib（含 numpy、pillow、fonttools 等传递依赖） | 视觉审计截图 | `requirements.txt` |
| playwright（含 pyee、greenlet） | 仅内部 replay 编排器使用 | `requirements.txt` |
| pytest、httpx | 测试 | `requirements-dev.txt` |
| vite（及 package-lock 中的传递依赖） | 仅开发期预览 | `package.json`、`package-lock.json` |

**ODA File Converter** 是使用者**自行安装**的外部程序（用于 DWG → DXF），
属于独立软件，其许可与再分发条款由该程序自身决定，本仓库不附带、不再分发。

## 3. 素材

| 文件 | 来源 | 状态 |
|---|---|---|
| `docs/assets/demo-scene.png`、`docs/assets/demo-export.png` | **由本仓库代码生成**，输入是代码生成的合成夹具（`tests/fixtures/generic_electrical_min.dxf`） | 可复现：`python tools_docs/make_demo_screenshots.py` |
| `docs/assets/demo-sanitized.png` | **已从仓库移除**（无法从仓库证据证明来源与可授权性；历史提交中仍存在） | 见 `RELEASE_READINESS.md` |
| `docs/generic-cad-eval.html` | 项目自有文档 | — |

`frontend/vendor/three/` 之外，仓库不含字体、图标库或其它第三方美术素材；
界面图标均为 CSS/内联 SVG（见 `frontend/index.html`、`frontend/css/style.css`）。

## 4. 再分发注意

1. 若把本仓库的代码用于再分发，**Three.js 的 `LICENSE` 文件与其版权/许可声明必须一并保留**
   （`frontend/vendor/three/LICENSE` 已随仓库提供，请勿删除）。
2. 若日后更新 `frontend/vendor/three/`，需同步更新该目录下的 `LICENSE` 与其版权年份。
3. 本文件**不是法律意见**，也不代表已对全部依赖的许可条款完成合规审查；
   正式对外分发前建议由维护者按其发布形态确认（尤其是打包/容器化场景下的声明保留方式）。

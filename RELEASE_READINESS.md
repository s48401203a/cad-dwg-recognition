# 发布就绪：许可证与公开范围决策项

本文件是给维护者的**决策材料**，不是法律意见。它只汇总仓库内的实际证据、需要决策的问题与可选方案。
**本仓库当前没有 `LICENSE` 文件，也没有声明整体许可证**；下文任何方案都**未被采纳**，
需要由维护者明确选择后才生效。

生成时间：2026-09-16（CST）。对应提交：见 PR #1 最新 commit。

---

## 1. 内容来源分类（基于仓库实际文件）

仓库当前被 Git 跟踪 **107 个文件**。按来源分为三类：

### 1.1 项目自有代码（可整体授权的前提）

| 范围 | 文件 |
|---|---|
| 后端 | `backend/**`（FastAPI 路由、`parser/` 的 DXF 读取与几何、`semantic/rule_engine.py`、`path_policy.py`、`security.py`、`share_tokens.py`、`storage.py`、`capabilities.py`、`exporting/`、`capture/`、`server.py`） |
| 前端 | `frontend/index.html`、`frontend/css/**`、`frontend/js/**`（含 `renderer/**`）、`frontend/share-config.js` |
| 配置与规则 | `backend/config/**`（`mapping.yaml`、`company_standards.yaml`、`model-catalog.yaml`、`profiles/**`） |
| 测试与合成夹具 | `tests/**`（含由代码生成的 `tests/fixtures/generic_electrical_min.dxf`） |
| 脚本与工程 | `start.sh`、`stop.sh`、`start-project.ps1`、`stop-project.ps1`、`install-env.*`、`*.bat`、`vite.config.js`、`package.json`、`package-lock.json`、`pyproject.toml`、`requirements*.txt` |
| 文档 | `README.md`、`GITHUB_PUBLISH_CHECKLIST.md`、`SPEC.md`（已标注历史文档）、`docs/generic-cad-eval.html`、`docs/assets/demo-sanitized.png` |
| CI | `.github/workflows/tests.yml` |

### 1.2 第三方代码与素材（必须保留其自身许可，不能被整体许可证覆盖）

| 内容 | 许可 | 证据 |
|---|---|---|
| `frontend/vendor/three/three.module.js` | **MIT** | 文件头含 `@license` 与 `SPDX-License-Identifier: MIT`；`const REVISION = '164'`（Three.js r164） |
| `frontend/vendor/three/examples/jsm/controls/OrbitControls.js` | MIT（随 Three.js 分发） | 与上同一 Three.js 发行版；文件内无独立许可头，**建议在再分发时保留上游 LICENSE 声明** |
| `frontend/vendor/three/examples/jsm/renderers/CSS2DRenderer.js` | 同上 | 同上 |
| npm 构建依赖（`vite` 等，仅开发预览用） | 各自许可（MIT 等） | `package-lock.json`；全部来自 `registry.npmjs.org`，**未引用私有 registry** |
| Python 运行/测试依赖（FastAPI、uvicorn、ezdxf、PyYAML、aiofiles、matplotlib、playwright、pytest、httpx 等） | 各自许可 | `requirements.txt`、`requirements-dev.txt`；仓库只声明依赖，不内嵌其代码 |

### 1.3 来源或授权尚不明确（建议在正式开源前确认）

1. **`docs/assets/demo-sanitized.png`**：无 EXIF、无水印元数据，画面为演示用界面截图，
   图内文字自述为通用示例（设备/线路/区域均为示例值），**未见客户名称与真实图纸内容**。
   但"该图由谁生成、是否可随项目授权"没有仓库内记录 → **需维护者确认**。
2. **`backend/semantic/rule_engine.py` 中的场地规则**（约 1.27 万行，含 `gatehouse`/快运/供应链相关
   推断常量与分支）：这些规则是在与某客户图纸长期交互中形成的经验规则，代码本身为项目自有，
   但**是否包含来自客户图纸的专有布局参数**需要维护者判断。仓库内**未见**客户图纸、坐标表或解析结果。
3. **`backend/config/profiles/express.yaml` / `supply-chain.yaml`**：内容为通用模块清单与默认数值
   （如月台摄像头到车尾间距），**未见客户专属参数**；确认后即可纳入公开范围。
4. **`.gitignore` 提及的 `backend/config/profiles/baishi-*.yaml`**：该文件**不在仓库内**（被忽略），
   属于本机客户覆盖配置。**保持排除**，不得公开。

### 1.4 明确不属于可授权范围（继续保持排除）

真实客户 DWG/DXF、`semantic.json` 与解析结果、客户项目目录与项目包、图纸截图、
运行日志与备份、`orchestrator/`（内部 replay 编排器）、`tools/`（内部脚本）、
`docs/` 下未跟踪的内部报告（含本决策材料所依据的评审文档）、任何凭据与 `.env`。

---

## 2. 许可证方案对比（均**未采纳**）

以下事实来源：MIT 许可证文本与说明见 OSI（<https://opensource.org/license/mit>）；
Apache-2.0 官方文本见 <https://www.apache.org/licenses/LICENSE-2.0>；
AGPL-3.0 官方说明见 GNU 项目（<https://www.gnu.org/licenses/agpl-3.0.html>）。具体条款以各官方文本为准。

| 方案 | 适用情形 | 优点 | 代价 / 风险 |
|---|---|---|---|
| **A. MIT** | 希望最大化采纳（工具属性、被人集成进内部系统） | 最短最易懂、OSI 认可、与现有 Three.js（MIT）一致；对使用者几乎无负担 | 不含专利许可条款；不要求衍生作品开源 |
| **B. Apache-2.0** | 希望被企业采用，且在意专利与贡献者条款 | 含明确的专利授权与专利报复条款、要求保留声明与变更说明、含贡献者条款 | 文本与合规义务比 MIT 重（需 `NOTICE` 等） |
| **C. AGPL-3.0** | 担心有人把本工具改成网络服务闭源运营 | 强 copyleft，网络使用也触发开源义务 | 会阻止一部分企业采用（内部合规常直接禁 AGPL）；与"想被广泛使用"的目标冲突 |
| **D. 暂时保持无许可证（现状）** | 先解决 1.3 的来源确认，再决定 | 不产生任何授权承诺，风险最低 | 公开可见 ≠ 已授权；他人使用/再分发在法律上仍受限，会明显降低复用价值 |
| **E. 其他**（如专有/双许可/CC 系列） | 有商业授权计划 | 可保留商业空间 | 需要额外流程与文本；**注意 CC 系列不适合软件代码** |

### 任何方案都不能覆盖的部分

- 1.2 的第三方内容继续受其**自身**许可约束（Three.js 的 MIT 声明必须保留）。
- 客户名称与商标不因代码许可而被授权。
- 1.3 中来源不明的素材（当前主要是 `docs/assets/demo-sanitized.png`）**不应**被整体许可证覆盖，
  除非维护者确认其可授权；否则应在选择许可证前替换为自建素材或移出仓库。
- **许可证不能追认已发生的行为**：仓库已公开，历史提交中曾出现的内部局域网地址
  （见 §3）不因日后选择许可证而消失。

---

## 3. 本轮检查发现（已修复 / 未修复）

| 项 | 状态 | 说明 |
|---|---|---|
| 导出与分享内容泄露本机绝对路径（配置文件的 `/Users/<name>/...`） | **已修复**（`267e79e`） | 改为仓库内相对路径，并加回归测试 |
| 被跟踪的 `frontend/share-config.js` 含真实内网地址 | **已修复**（`267e79e`） | 清空为自动探测；`.gitignore` 加固 |
| **历史提交中仍含该内网地址** | **未修复（不做）** | 该内容存在于已推送的历史中；清除需要改写历史并强推，**本任务未授权**。影响：暴露了一个私有网段地址（非凭据）。建议由维护者决定是否处理；**改回 Private 不能撤回已发生的公开暴露** |
| 全仓库扫描（107 个跟踪文件 + 全部历史提交）：凭据 / 私钥 / `.env` / 数据库 | **未发现** | 扫描模式：常见令牌前缀、私钥头、`password=`、`api_key=` |
| 客户图纸 / `semantic.json` / 导出产物 / 图纸截图 | **未发现**（当前与历史均无新增记录） | 唯一 DXF 为代码生成的合成夹具；唯一图片为演示图 |
| 客户名称出现位置 | **公开信息，非泄露** | 仅出现在"默认 profile 是通用、客户 profile 可选"的说明文字与 `docs/generic-cad-eval.html` 的评测说明中；未见地址、布局、设备编号等业务数据 |
| CI 附件内容 | **未发现敏感内容** | 仅上传 `exports/eval/latest/`（合成用例的评估报告），实测报告内无本机路径与私网地址，只有合成用例名 |
| 第三方素材许可与归属 | **已核实**（见 1.2） | Three.js r164 保留 MIT 声明；npm 依赖不内嵌；未引用私有 registry |
| 跟踪文件中含本机绝对路径 | **未发现** | 现 HEAD 扫描为 0 命中 |

**检查覆盖范围与限度**：本轮扫描了当前全部跟踪文件、`c2f81db..HEAD` 的完整差异、
以及仓库可获取的全部提交历史（`git log --all`），使用本地命令完成，**未将仓库或任何图纸上传第三方扫描服务**。
即便如此，本检查**不能保证不存在任何未被模式识别的敏感内容**，也**不能清除已被外部克隆或抓取的内容**。

---

## 4. 维护者需要决定的事项（一次性选择）

**问题 1：整体许可证（必答）**

- A. 采用 **MIT**
- B. 采用 **Apache-2.0**
- C. 采用 **AGPL-3.0**
- **D. 暂不许可，先解决"来源不明项"（`docs/assets/demo-sanitized.png` 等）**
- E. 其他（请指定）

**问题 2：公开范围（可多选，默认保持现状）**

- A. 保持现状：只公开通用源码 + 合成样例 + 公开文档；`orchestrator/`、`tools/`、客户配置与内部报告继续排除
- B. 额外公开 `docs/` 下某些文档（需逐份指定，并确认不含内部背景）
- C. 额外公开 `tools/` 中的通用脚本（需逐份确认无客户路径与内部依赖）
- D. 不公开任何额外内容，但把内部报告的**通用摘要**继续补充进 README

**问题 3：历史中的内部地址（必答）**

- A. 不处理，仅在文档中记录（推荐：影响为私有网段地址，非凭据，且历史改写有成本与风险）
- B. 授权改写历史并强推（需明确授权；会影响所有已克隆副本与 PR 引用）
- C. 其他（请指定）

**问题 4：`docs/assets/demo-sanitized.png`（必答）**

- A. 确认可随项目授权 → 纳入公开范围
- B. 无法确认 → 在正式开源前替换为自建素材或移出仓库

---

## 5. 阻塞关系说明（区分代码合并与正式开源发布）

| 事项 | 是否阻塞合并 PR #1 | 是否阻塞"正式开源发布/对外宣称已授权" |
|---|---|---|
| 整体许可证未定 | **不阻塞**。代码合并到分支不改动授权状态 | **阻塞**。无许可证时对外只能说"源码公开可见"，不能说"已开源可自由使用" |
| `demo-sanitized.png` 来源未确认 | 不阻塞 | **阻塞**（问题 4 选 B 时需先替换/移除） |
| 历史中的内部局域网地址 | 不阻塞 | 不阻塞，但建议一并决定（问题 3） |
| 第三方许可（Three.js MIT） | 不阻塞，已在文件中保留声明 | 不阻塞；若日后调整 vendor 需继续保留 |
| Windows / HTTPS / 多进程 / DWG 转换未验证 | 不阻塞 | 不阻塞，但**不得**在对外材料中描述为已验证 |

---

## 6. 建议的默认路径（需维护者确认后才执行）

1. 先回答问题 4（素材可授权性）与问题 1；若问题 1 选 D，则先替换来源不明素材，再选许可证。
2. 问题 2 保持现状，问题 3 选 A。
3. 许可证确定后再在仓库根添加 `LICENSE`，并在 `README.md` 更新「许可证」小节与
   `docs/generic-cad-eval.html` 的相关说明，使其与所选许可证一致。
4. 在此之前，对外描述建议统一为："源码已公开可查看；许可证尚待维护者确定，
   在确定前请勿视为已获得使用授权。"

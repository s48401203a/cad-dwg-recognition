# 发布就绪：来源核实、许可证与公开范围决策项

本文件是给维护者的**决策材料**，不是法律意见，也不代替维护者的授权决定。
它只汇总仓库内**可核查的证据**、需要决策的问题与可选方案。

**本仓库当前没有 `LICENSE` 文件，也没有声明整体许可证**；下文任何方案都**未被采纳**。

> **重要原则**：**"没有发现客户信息"不等于"有权公开授权"**。
> 扫描无命中只能说明没有发现特定模式的敏感内容；**授权来源需要正向证据**
> （生成脚本、上游许可、明确的自有条件）。凡是缺少正向证据的内容，本文件一律标为
> **待维护者确认**，不写成"自有可授权"。

生成时间：2026-09-16（CST）。对应提交：见 PR #1 最新 commit。

---

## 1. 内容来源分类

仓库当前被 Git 跟踪 **107 个文件**（本轮变更后数量见 PR diff）。按**证据强度**分为四类：

### 1.1 有正向证据可确认为项目自有

| 范围 | 证据 |
|---|---|
| 后端源码 `backend/**` | 本仓库开发分支的历史提交；无第三方来源标记 |
| 前端源码 `frontend/index.html`、`frontend/css/**`、`frontend/js/**` | 同上；界面文案为项目自有中文文案 |
| 识别规则与配置 `backend/config/**` | 见 §2.3 的针对性核实结果 |
| 测试与合成夹具 `tests/**` | **夹具由代码生成**，生成脚本在仓库内：`tests/synthetic.py`、`tests/eval/make_generic_fixture.py`；可复现 |
| 脚本与工程文件 | `start.sh`、`stop.sh`、`start-project.ps1`、`stop-project.ps1`、`install-env.*`、`vite.config.js`、`pyproject.toml`、`requirements*.txt` 等 |
| 文档 | `README.md`、`GITHUB_PUBLISH_CHECKLIST.md`、`SPEC.md`（已标注历史）、`docs/generic-cad-eval.html`、`RELEASE_READINESS.md`、`THIRD_PARTY_NOTICES.md` |
| 演示截图 `docs/assets/demo-scene.png`、`docs/assets/demo-export.png` | **本轮新增**，生成脚本在仓库内且输入为合成夹具：`tools_docs/make_demo_screenshots.py`（可复现） |
| CI `.github/workflows/tests.yml` | 项目自有 |

### 1.2 第三方内容（有上游许可证据，须保留其声明）

| 内容 | 许可 | 证据 |
|---|---|---|
| `frontend/vendor/three/**`（Three.js r164，含 2 个 addons） | **MIT**（`Copyright © 2010-2024 three.js authors`） | 上游 r164 的 `LICENSE` 全文：<https://raw.githubusercontent.com/mrdoob/three.js/r164/LICENSE>；本仓库已随附副本 `frontend/vendor/three/LICENSE` |
| 依赖声明（未内嵌源码） | 各自许可 | `requirements*.txt`、`package.json`、`package-lock.json` |

详见 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)（本轮新增，含"SPDX 标识不等于义务已履行"的说明与补齐记录）。

### 1.3 缺少正向证据 → **待维护者确认**（不得视为已授权）

| # | 内容 | 证据核查过程 | 结论 |
|---|---|---|---|
| Q1 | `backend/semantic/rule_engine.py` 中的**图纸坐标常量**：`PLAN_COPY_START_X_MM = 2_939_888.0`、`PLAN_COPY_OFFSET_X_MM = 178_200.0`、`PLAN_COPY_COUNT = 4`、`PLAN_MIN_Y_MM = -1_055_000.0`、`PLAN_MAX_Y_MM = -760_000.0` | 这些字面量只出现在 `_legacy_plan_copy_index()`（约 12162 行）及其两个调用点；函数名含 `legacy`，但**调用点没有开关**，会参与通用解析路径。仓库内**没有**任何说明这些数值来源的文档或注释 | 数值看起来来自某张具体图纸的坐标空间（图幅间隔 178,200 mm、Y 范围 295 m）。**无法从仓库证据确认其来源与可授权性** |
| Q2 | 同文件中的**设备编号前缀与编号范围写法**（原为硬编码正则与按型号的前缀列表，**未在此展示具体值**） | 仅出现在规则引擎内部；仓库内无来源说明 | 这些前缀是**特定项目命名体系**的样式。**无法确认是否为通用行业约定**，也无法确认其来源。**已按维护者授权移出公开代码**（见 §2.4） |
| Q3 | 演示图 `docs/assets/demo-sanitized.png`（**本轮已从仓库移除**） | 该文件由 `01918e7` / `6d52602` 引入；仓库内**没有**生成脚本、没有 EXIF/文本元数据。画面内英文界面文字（如 `Layers`、`Object Info`、`Private repo safe`）与本仓库前端的中文文案**不一致** | 该图**并非由本仓库代码生成**，来源无法从仓库证据证明。已移除以避免把来源不明素材当成自有素材分发；**历史提交中仍存在** |
| Q4 | `backend/config/profiles/express.yaml`、`supply-chain.yaml` | 见 §2.3：内容为通用模块清单与默认数值 | 文件本身未见客户专属内容，但**其规则是否源自客户约定应由维护者确认**（判断依据不在仓库内） |

> Q1/Q2 属于**业务规则来源**问题，不是"敏感信息泄露"问题：它们可能包含某项目的命名与坐标约定，
> 但仓库内**没有**客户图纸、编号清单或解析结果。是否可授权、是否应改为可配置项，
> 需要维护者判断——本仓库**不擅自删除业务代码**（那会改变功能行为），也不宣称其可授权。

### 1.4 明确排除在公开范围之外

真实客户 DWG/DXF、`semantic.json` 与解析结果、客户项目目录与项目包、图纸截图、
运行日志与备份、`orchestrator/`（内部 replay 编排器）、`tools/`（内部脚本）、
`docs/` 下未跟踪的内部报告、任何凭据与 `.env`。

---

## 2. 本轮针对性来源核实（按对象）

### 2.1 `docs/assets/demo-sanitized.png`

- **历史**：`git log --all --follow` → 仅 `01918e7`、`6d52602` 两次提交引入，无生成脚本。
- **可核查线索**：文件无 EXIF、无文本元数据；画面为英文界面演示。
- **与本仓库的关系**：本仓库前端（`frontend/index.html`）的界面文案为中文
  （如「项目」「图层控制」「对象信息」「识别统计」），与该图的英文界面不符 → **不是本仓库产物**。
- **处理**：本轮**移除**该文件与 README 引用（不伪造替代内容）；`docs/assets/` 改为放**本仓库生成**的
  `demo-scene.png` 与 `demo-export.png`。
- **可复现生成方法**：

  ```bash
  pip install -r requirements.txt
  # 需要 Playwright 浏览器；脚本默认使用本机 Chrome（channel="chrome"）
  python tools_docs/make_demo_screenshots.py
  ```

  脚本做三件事：在**临时运行目录**启动 `backend/server.py`（回环、无令牌）→ 通过页面真实文件输入上传
  `tests/fixtures/generic_electrical_min.dxf`（合成夹具）→ 截取 3D 场景与静态导出页。
  **不读取任何客户图纸**，导出内容不含本机绝对路径。
- **历史遗留**：该旧图**仍存在于历史提交**中。清除需改写历史并强推，本任务未授权（见 §5 问题 3）。

### 2.2 场地规则（`rule_engine.py`）

| 检查角度 | 结果 |
|---|---|
| 注释中是否提到图纸名/项目名/客户 | **未发现**（`grep` 注释中的"现场/图纸/项目/客户"关键词无命中） |
| 是否有客户名称常量 | **未发现**（`百世`/`南昌`/`gatehouse` 客户名不出现；存在中性的 `gatehouse_*` 规则集标识） |
| 是否存在图纸相关坐标常量 | **发现**（Q1：5 个 `PLAN_*` 常量，用于 `_legacy_plan_copy_index`） |
| 是否存在项目命名体系样式 | **发现**（Q2：`AP_LABEL_PREFIX_PATTERN` 与若干 `label_prefixes`） |
| 仓库内是否存在客户图纸/解析结果作为对照 | **不存在**（`git log --all --diff-filter=A` 无客户图纸、无 `semantic.json`、无导出产物） |

结论：**未发现客户身份信息或图纸内容**；但 **Q1/Q2 的规则来源无法从仓库证据确认**，列入 §5 待确认清单。
本轮**未删除**这些规则（避免改变功能行为），也**未宣称**其可授权。

### 2.3 `express.yaml` / `supply-chain.yaml` / `generic.yaml`

- 三个文件均为**声明式配置**：`id` / `display_name` / `site_type` / `standards_overrides` /
  `active_modules`（或 `future_modules`）/ 空的 `rule_overrides`。
- 内容为**通用模块清单与默认数值**（如月台摄像头到车尾间距 `5.0 m`、库墙高 `10.5 m`），
  **未见**客户名称、地址、设备编号或图纸坐标。
- 加载方式：仅当调用方**显式传入**对应 `site_profiles` 时才加载
  （`RuleEngine._load_selected_profile_configs`），默认 profile 是 `generic`。
- 结论：文件内容本身无客户专属数据；**其规则是否源于客户约定**需维护者确认（Q4）。

### 2.4 已按维护者授权执行的隔离（A2 + D1）

维护者已确认：**设备编号前缀属客户命名规范**（A2），**项目文档名/方案名样式与 A2 同类**（D1），
并授权将其移出公共代码。已执行的最小隔离：

| 移出的内容 | 原位置 | 现位置 |
|---|---|---|
| 设备编号前缀与编号范围写法（正则与按型号前缀列表） | `rule_engine.py` 模块级常量 | 本机私有 `site-adaptations.yaml` 的 `label_patterns` / `label_range_patterns` |
| 项目/方案名称关键词 | `rule_engine.py` 硬编码元组 | 私有配置 `project_name_keywords` |
| 主平面图框标题中的方案名 | `rule_engine.py` 多处字面量 | 中性常量 `MAIN_PLAN_TITLE`（前端同步为中性标题） |
| 图层名关键词（项目文档名样式） | `mapping.yaml` 的 `layer_rules.*.keywords` | 公共配置仅保留通用词；项目样式由私有配置 `extra_rule_keywords` / `extra_layer_keywords` 追加 |
| 项目专属"数量注释"正则 | `rule_engine.py` 内联正则 | 私有配置 `extra_quantity_patterns` |

**性质说明**：这是**内容移出公开代码**，不是"默认关闭"。公共版本不再包含这些字面量，
未配置时相关分支自然不命中（`tests/test_site_adaptations.py` 双向验证：
未配置→不匹配、配置后→恢复生效）。

**未移出的内容及理由**：

- 图纸坐标范围规则（`PLAN_*` 常量）：维护者答复为**通用**（B2），保留在公共代码。
- 场地规则数值（快运/供应链）：维护者答复"不确定"（A4=不确定），且实测**仅在非 `generic` 模式生效**
  （`_site_metadata()` 对 generic 直接返回，不写入这些数值），配置文件本身也未见客户专属数据，
  因此保持现状；如需进一步隔离，应按配置项处理而非删除。
- `docs/assets/demo-sanitized.png`：已在上一轮从 HEAD 移除（历史中仍存在，维护者选择不清除历史）。

---

## 3. 第三方许可声明的核对与补齐

| 项 | 状态 |
|---|---|
| `three.module.js` | 原本只有 `@license` + `SPDX-License-Identifier: MIT` + 版权行，**缺少 MIT 要求的完整许可声明文本** |
| `examples/jsm/controls/OrbitControls.js`、`examples/jsm/renderers/CSS2DRenderer.js` | 原本**完全没有**版权与许可声明 |
| 本轮处理 | 新增 `frontend/vendor/three/LICENSE`（上游 r164 官方全文），并新增 `THIRD_PARTY_NOTICES.md` 记录版本、著作权、上游链接、是否修改 |

MIT 的条件原文（上游 r164 `LICENSE`）：
"The above copyright notice and this permission notice shall be included in all copies or
substantial portions of the Software."

**SPDX 标识只是机器可读的许可标识，本身不构成许可义务的履行**——版权声明与许可声明文本才是明文要求。

---

## 4. 许可证方案对比（均**未采纳**；以下为事实性说明，非法律结论）

官方来源：MIT 文本与说明见 OSI <https://opensource.org/license/mit>；
Apache-2.0 官方文本见 <https://www.apache.org/licenses/LICENSE-2.0>；
AGPL-3.0 官方说明见 GNU 项目 <https://www.gnu.org/licenses/agpl-3.0.html>。具体条款以各官方文本为准。

| 方案 | 适用情形 | 优点 | 代价 / 风险 |
|---|---|---|---|
| **A. MIT** | 希望最大化被采纳（工具属性、被集成进他人系统） | 文本最短最易懂、OSI 认可、与随仓库分发的 Three.js（MIT）一致 | 不含专利许可条款；不要求衍生作品开源 |
| **B. Apache-2.0** | 希望被企业采用，且在意专利与贡献者条款 | 含专利授权与专利报复条款；含贡献者条款 | 合规义务比 MIT 重；**是否产生额外义务（例如随分发提供 NOTICE 文件）取决于是否存在上游 NOTICE 以及具体分发形态**，不能一概而论 |
| **C. AGPL-3.0** | 担心有人把本工具改成网络服务闭源运营 | 强 copyleft，网络使用也触发开源义务 | 会挡住一部分企业采用；与"想被广泛使用"的目标冲突 |
| **D. 暂时保持无许可证（现状）** | 先完成 §5 的来源确认 | 不产生任何授权承诺 | 公开可见 ≠ 已授权；他人使用/再分发在法律上仍受限，明显削弱复用价值 |
| **E. 其他**（专有 / 双许可 / 其他 OSI 许可） | 有商业授权或特定分发计划 | 可保留商业空间 | 需额外流程与文本；**注意 Creative Commons 系列不是为软件代码设计的**，不适合用于代码许可 |

### 任何整体许可证都不能覆盖的部分

- §1.2 的第三方内容继续受其**自身**许可约束（Three.js 的 MIT 声明必须随再分发保留）。
- §1.3 中缺少正向证据的内容（Q1–Q4）**不应**被整体许可证覆盖，除非维护者确认其可授权。
- 客户名称与商标不因代码许可而被授权。
- **许可证不能追认已发生的行为**：仓库已公开，历史提交中的内容（如已移除的演示图、历史中的内网地址）
  不因日后选择许可证而消失。

---

## 5. 维护者需要决定的事项（一次性选择）

**问题 1：下列内容中，哪些由你确认拥有公开授权？**（可多选；若无，请选"无"）

- Q1 `rule_engine.py` 中的 `PLAN_*` 图纸坐标常量（`_legacy_plan_copy_index`）
- Q2 `rule_engine.py` 中的编号前缀规则（`AP_LABEL_PREFIX_PATTERN` 与 `label_prefixes`）
- Q3 历史提交中的旧演示图 `docs/assets/demo-sanitized.png`（当前已从 HEAD 移除）
- Q4 `express.yaml` / `supply-chain.yaml` 中的场地规则约定
- **无**（以上均无需确认，或你确认均可公开）
- 其他（请说明）

> 说明：若某项**无法确认**，建议的处置是"改为可配置项 / 从公开范围移出 / 保留现状但不作授权声明"，
> 由维护者选择；本仓库**不会**在未获确认时删除业务代码或宣称其可授权。

**问题 2：整体许可证（必答）**

- A. MIT　B. Apache-2.0　C. AGPL-3.0　**D. 暂不许可，先解决问题 1**　E. 其他（请指定）

**问题 3：历史遗留内容（必答）**

- A. 不处理，仅在文档中记录（推荐；改写历史有成本与风险）
- B. 授权改写历史并强推（影响所有已克隆副本与 PR 引用）
- C. 其他

---

## 6. 阻塞关系（区分"代码合并"与"正式开源发布"）

| 事项 | 阻塞合并 PR #1？ | 阻塞"正式开源发布 / 对外宣称已授权"？ |
|---|---|---|
| 整体许可证未定 | **否** | **是** |
| Q1–Q4 来源未确认 | **否**（不改变代码行为） | **是**（未确认内容不应被整体许可证一并覆盖） |
| 历史中的旧演示图与内网地址 | 否 | 否（建议一并决定） |
| 第三方声明 | 否（本轮已补齐 Three.js 的 MIT 声明义务） | 否 |
| Windows / HTTPS / 多进程 / DWG 转换未验证 | 否 | 否（**不得**在对外材料中描述为已验证） |

在问题 1、2 解决前，对外描述建议统一为：
**"源码已公开可查看；许可证与部分素材授权尚待维护者确认，暂不视为已获得使用授权。"**

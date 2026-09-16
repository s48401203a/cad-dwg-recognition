# CAD 强弱电 3D 读取器

通用开源 CAD 强弱电读取与 3D 预览工具。上传 DWG/DXF 后，按图层、块名、文字识别墙体、桥架、摄像头、AP、机柜、配电、照明等对象，并生成 Three.js 3D 场景。

本仓库服务的是**通用强弱电图纸**，不是只服务某一客户。弱电与强电走同一条读取链路。默认场地包是 `generic`。百世快运 `express`、供应链 `supply_chain` 是可选场地包，需要月台、车尾、炮楼等场地推断时再显式启用。

![脱敏演示图](docs/assets/demo-sanitized.png)

评测说明见 [`docs/generic-cad-eval.html`](docs/generic-cad-eval.html)（可用 `file://` 打开）。

---

## 快速开始（自包含，不需要额外脚本）

只依赖仓库内被跟踪的文件。首次运行会自动创建 `.venv` 并安装 `requirements.txt`。

macOS / Linux：

```bash
./start.sh                # 回环地址 + 自动挑端口（8000-8020）+ 自动打开浏览器
./start.sh --no-open      # 不打开浏览器
./start.sh --port 8000    # 指定端口
./stop.sh                 # 停止
```

然后访问 `http://127.0.0.1:<端口>/`（脚本会打印实际地址）。健康检查：`GET /api/health`。

Windows：

```powershell
.\start-project.ps1        # 或双击「启动项目.bat」
.\stop-project.ps1
```

页面由 FastAPI 直接提供（原生 JS + Three.js，**没有构建步骤**，默认不需要 Node.js）。

可选：需要 Vite HMR 时 `./start.sh --vite`（需要 Node.js）；直接运行后端也可以：

```bash
python backend/server.py --port 8000 --no-open
```

### 局域网访问（显式开启 + 必须鉴权）

默认只监听回环地址。局域网模式必须显式开启，并会自动生成访问令牌：

```bash
./start.sh --lan           # 自动生成令牌并打印带 token 的访问地址
# 或
CAD_ACCESS_TOKEN=<你的令牌> python backend/server.py --host 0.0.0.0 --port 8000
```

未设置令牌时，绑定非回环地址会被拒绝启动（不会以无鉴权状态暴露到局域网）。

**局域网模式下，未认证的访问者无法枚举、读取或导出任何项目与图纸内容**，也不能连接日志 WebSocket；
首次打开页面会看到登录界面，粘贴令牌即可（详见下文「访问模型与安全边界」）。
令牌会显示在启动日志里，只应发给可信同事；转让后可用顶栏「退出登录」清除本机会话。

---

## 能力矩阵（干净 checkout 实测）

`GET /api/health` 返回 `capabilities`，前端据此隐藏/禁用不可用入口——不会出现「按钮在、点下去必然失败」的情况。

| 能力 | 干净检出 | 依赖 | 不可用时的表现 |
|---|---|---|---|
| `dxf_parse` DXF 解析 | ✅ 可用 | `ezdxf` | 返回 503 并说明缺少依赖 |
| `dwg_convert` DWG → DXF | ⚠️ 取决于本机 | ODA File Converter | 上传 DWG 返回 503，并明确提示「DXF 不受影响，可直接上传 DXF」 |
| `static_export` 静态导出 | ✅ 可用（仓库内置导出器） | 无额外依赖 | 返回 503 + 原因 |
| `share_link` 分享链接 | ✅ 可用 | 同静态导出 | 返回 503 + 原因 |
| `visual_audit` 视觉审计截图 | ✅ 可用 | `matplotlib` | 返回 503 + 原因 |
| `replay` 逐图层复原编排 | ❌ 默认不可用 | 内部 `orchestrator/` + Playwright | 全部端点返回 503，`/api/replay/status` 也报告 `available: false` |

**`replay` 说明：** 逐图层复原校验依赖内部编排器 `orchestrator/`，该目录**不在公开仓库内**（被 `.gitignore` 排除）。本地若部署了该模块，可用 `CAD_ENABLE_REPLAY=1` 打开，或用 `CAD_REPLAY_RUNNER=<模块名>` 指向自定义 runner。

**DXF 不需要 ODA。** ODA File Converter 只用于 DWG → DXF 转换；缺失它不影响 DXF 图纸的全部功能。

---

## 访问模型与安全边界

本工具定位是**本机单用户工具**，不是公网服务。

### 默认（回环 + 未配置令牌）

零摩擦：本机打开页面即可上传、解析、摆放、导出，无需登录。

### 启用访问令牌后（`CAD_ACCESS_TOKEN`，或局域网模式 `--lan`）

**默认拒绝 + 显式白名单**。这时未经认证的访问者**不能枚举、读取或导出任何项目与图纸内容**：

| 访问面 | 未认证时的行为 |
|---|---|
| `/api/**`（项目列表、项目详情、语义数据、导出、模型覆盖、项目包、站点配置、模型目录、单位、replay 状态与日志…） | **401**，且响应体不含项目 ID/名称/图纸数据 |
| `/exports/**`（静态导出 HTML 及其关联文件） | **401**，`GET` 与 `HEAD` 都不放行 |
| `/ws/logs`（实时日志 WebSocket） | 握手被拒绝（close 1008） |
| `/api/health` | 200，但只返回 `ok` / `auth_required` / 各能力是否可用；**不回显本机路径与 ODA 路径** |
| `/api/auth/session`、`/api/auth/login`、`/api/auth/logout` | 匿名可用（这是登录入口本身） |
| `/`、`index.html`、`*.js`、`*.css`、`/vendor/**`、`/share-config.js` | 匿名可用（否则连登录界面都加载不出来；这些文件来自公开仓库，不含项目内容） |

**Host / Origin / CORS 只防跨源滥用，不是身份认证。** 不带 `Origin` 的脚本客户端（curl / 脚本）
同样必须携带令牌，否则 401。

### 浏览器登录体验

1. 未认证打开页面会显示**登录界面**，粘贴访问令牌即可。
2. 登录成功后服务端设置一个 **HttpOnly 会话 cookie**（`cad_session`），此后 API 调用、
   WebSocket 与**直接点开 `/exports/` 下的导出文件**都能通过校验——`<a href>` 无法附带自定义请求头，
   会话 cookie 是唯一可行方式。
3. 令牌只保存在本机浏览器（`localStorage` + HttpOnly cookie），**不写入日志、不写入导出内容、不出现在分享链接里**。
4. 令牌错误或会话过期时，界面会明确提示「访问令牌不正确」并停留在登录界面，重新输入即可恢复。
5. 认证模式下顶栏有「退出登录」入口，会清除会话 cookie 与本机保存的令牌。

启动脚本带令牌打开浏览器时使用 `http://127.0.0.1:<端口>/?token=<令牌>`；前端会立刻把 URL 里的
令牌清掉（`history.replaceState`），避免留在浏览器历史里。

### 分享链接

**分享默认需要认证。** 同时提供了一种**作用域分享令牌**，让未认证的人也能看某一个导出页：

- 由 `POST /api/projects/{id}/share-link` 生成（会**写文件**，因此是 POST，不是可被预取的 GET）。
  `GET` 形式保留兼容，但只返回"需要认证"的链接，**不签发**分享令牌。
- 分享令牌与主访问令牌**完全独立**：由随机数生成，无法从主令牌推导，也**不能**用于任何 `/api/*`。
- **作用域限定到那一个导出文件**：访问其他项目、其他导出文件或任何 API 都是 401。
- **可过期、可撤销**：默认有效期 `CAD_SHARE_TTL_HOURS`（24 小时）；
  `GET /api/projects/{id}/share-tokens` 列出（**不回显令牌本身**），
  `DELETE /api/projects/{id}/share-tokens` 撤销该项目的全部分享令牌。
- 分享链接形如 `http://<host>/exports/static-pages/<项目>/<文件>.html?share=<分享令牌>`；
  **链接中不含主访问令牌**。把链接转发出去等于把该导出页的查看权交给对方，直到过期或被撤销。
- 签发失败时会如实返回 `share_error`，并退回"需要认证"的链接，**不会**给出无保护的链接。

### 其它边界

- **默认只监听 `127.0.0.1`。** 绑定非回环地址必须显式开启局域网模式 **且** 设置访问令牌，否则拒绝启动。
- **同源校验。** 浏览器请求的 `Origin`/`Referer` 必须与请求 `Host` 一致，或落在显式配置的开发来源里（`CAD_DEV_ORIGINS`，默认含 Vite 的 5173/5174）。跨源读写一律 403。
- **Host 校验。** 非回环、非显式配置的 `Host` 直接 403，防 DNS rebinding。
- **客户端只提交 ID，不提交路径。** 图纸/项目的文件路径一律由服务端解析，并校验落在允许根目录内；绝对路径、`..`、符号链接越界、跨平台路径（`C:\`、UNC）全部拒绝。同一策略覆盖读取、保存、导出、归档、恢复、打开文件与项目包导入。
- **导出内容不泄露本机路径。** 项目导出、静态导出页都不会包含 `save_dir`、`semantic_path` 等本机绝对路径。
- **上传边界。** 默认上限 512 MB（`CAD_MAX_UPLOAD_MB`），流式写入超限即中止并清理临时目录；解析并发上限 `CAD_PARSE_CONCURRENCY`（默认 CPU 核数的一半）。

在受管目录之外保存的历史项目需要显式授权：设置 `CAD_ALLOWED_PROJECT_ROOTS`（路径分隔符分隔）。未授权时这些项目只读可解析，不会写回本机其它目录。

### 相关环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `CAD_HOST` | `127.0.0.1` | 绑定地址 |
| `CAD_PORT` | 自动挑 8000-8020 | 监听端口 |
| `CAD_LAN_MODE` | 关 | 设为真值即绑定 `0.0.0.0`（需令牌） |
| `CAD_ACCESS_TOKEN` | 空 | 访问令牌 |
| `CAD_DEV_ORIGINS` | Vite 5173/5174 | 允许的额外浏览器来源，逗号分隔 |
| `CAD_ALLOWED_HOSTS` | 空 | 允许的额外 `Host` 头 |
| `CAD_MAX_UPLOAD_MB` | `512` | 上传大小上限 |
| `CAD_PARSE_CONCURRENCY` | CPU/2 | 同时进行的解析数 |
| `CAD_ALLOWED_PROJECT_ROOTS` | 空 | 显式登记的受信项目根目录 |
| `CAD_RUNTIME_ROOT` | `backend/` | 运行期数据根（项目/上传/日志） |
| `CAD_ENABLE_REPLAY` | 自动探测 | 强制开启/关闭 replay |
| `CAD_SHARE_TTL_HOURS` | `24` | 分享令牌有效期（小时） |
| `CAD_SHARE_TOKENS_PATH` | 运行期目录下 `share/share-tokens.json` | 分享令牌存储位置 |

---

## 单位与几何

- 内部坐标统一为**毫米**。`$INSUNITS` 完整映射（`1 in = 25.4 mm`、`2 ft = 304.8 mm`、`4 mm`、`5 cm`、`6 m`、`21 US survey ft` 等）。**10 英尺 = 3048 毫米**。
- **无单位（`$INSUNITS=0`）与未知单位码不会被静默当作毫米**：解析结果带 `unit_unspecified` 与 `unit_warning`，可用 `GET /api/units` 列出可选项，并在解析请求里用 `unit` / `unit_scale_to_mm` 显式指定。
- **多段线 bulge**（凸度）被完整支持：长度包含真实弧长，闭合多段线计入闭合边；`geometry.segments` 给出逐段的直线/圆弧描述（圆心、半径、起止角、弧长），`geometry.curve_points` 提供按弦高误差（默认 5 mm）离散后的折线，供渲染画弧而不是画弦。
- **ARC 弧长**按 DXF 语义计算（逆时针 `start → end`，`(end-start) mod 360`），270° 的弧不会被当成 90°。
- **块引用变换**（旋转、镜像/负缩放、非均匀缩放、嵌套）按实体 OCS 正确展开；镜像块曾丢失插入点平移，现已修复并加回归测试。
- 每个实体保留 `source_entity_id`（DXF handle），预览坐标可回溯原始实体。

---

## 数据存储与并发

- `backend/storage.py` 只负责**服务端管理的路径**：项目 ID、图纸 ID 先校验再拼路径。
- 所有 JSON 写入是**原子写**（同目录临时文件 + `fsync` + `os.replace`）；写中断不会破坏旧文件。
- read-modify-write 全过程持有文件锁（进程内可重入锁 + POSIX `flock`），并发上传/保存不丢更新。
- 项目与人工摆放（overrides）都带 **revision**；旧版本保存返回 **409 冲突**，不会覆盖别人的新修改。
- JSON 损坏**不再静默当空数据**：原文件被隔离为 `*.corrupt-<时间戳>` 并返回明确错误，可从隔离副本恢复。
- **人工摆放与规则推断分开存储**：人工校正写在 `model-overrides/model-overrides.json`，重新解析只新增图纸记录，不会清空人工结果。

---

## 默认 profile

| Profile | 作用 |
|---|---|
| `generic` | **默认**。只按图层 / 块 / 文字读墙、桥架、摄像头、AP、机柜、配电、照明；不启用月台、车尾、炮楼推断。 |
| `express` | 可选快运场地包。月台、车尾摄像头、射灯、鱼眼 / 半球等。 |
| `supply_chain` | 可选仓储供应链场地包。货架 / 工位 / 分拣 / DWS 按场地规则渐进启用。 |

解析请求携带 `site_profiles`。不传或只传 `generic` 时走通用读取；**场地专用推断不会被隐式启用**。

```json
{ "file_id": "<upload_id>", "site_profiles": ["generic"] }
```

可用 `GET /api/site-profiles` 查看登记列表。

## 使用流程

1. 启动后打开本地页面。
2. 上传 DWG 或 DXF（DXF 无需 ODA）。
3. 解析默认走 `generic`。需要场地推断时再显式启用 `express` / `supply_chain`。
4. 后端用 ezdxf 读实体（DWG 先经 ODA 转 DXF），规则引擎生成语义结果。
5. 前端 Three.js 生成 3D。用图层开关、视角和对象信息面板查看。
6. 需要人工摆放时，在「摆放试验场」项目里摆放/移动/撤销并保存；保存的是独立 overrides。

---

## 测试与评测

安装测试依赖（与运行依赖分开）：

```bash
pip install -r requirements-dev.txt      # 需要 httpx（TestClient）与 pytest
python -m pytest tests/ -q
```

公开合成夹具严格评估：

```bash
python -m tests.eval.runner --fixtures-only --strict
```

`--strict` 会把 desired / geometry 缺口也视为失败（退出码 2）。公开夹具矩阵覆盖：基本强弱电、空图、英尺/米/毫米、无单位、弧形与闭合多段线、块变换（旋转/镜像/非均匀缩放/嵌套）、重复图例、未知块、畸形输入与不支持的实体类型。夹具全部由 `tests/synthetic.py` 现场生成到临时目录，**运行测试不会修改被跟踪的夹具文件**。

测试依赖说明：HTTP 层测试需要 `httpx`（Starlette `TestClient` 的依赖）。它已在 `requirements-dev.txt` 中显式固定；缺少时测试会明确报错，而不是静默跳过——不会去改动全局环境。

私有历史回归：

```bash
python tests/regression_counts.py     # 需要本机已有解析结果
```

**CI：** `.github/workflows/tests.yml` 在 Python 3.10 与 3.12 上跑 `pytest tests/` 与 `runner --fixtures-only --strict`，不需要 ODA、不需要客户数据。

---

## 隐私与发布边界

以下内容**永不入库**：

- 客户 `*.dwg` / `*.dxf`（公开合成夹具 `tests/fixtures/**/*.dxf` 由代码生成，不含客户数据）
- `semantic.json` 与解析结果
- 客户项目目录（`backend/projects/`、`backend/uploads/`、`projects/` 等）
- 日志、备份、评测导出、本机运行状态（`.cad-runtime/`）

`.gitignore` 按目录屏蔽客户资料与内部工具（`orchestrator/`、`tools/`、多数 `docs/`）。**不会**为了提交而整体放开这些屏蔽。

`SPEC.md` 与 `AGENTS.md` 是早期设计文档，其中的 Vue/Pinia 方案**仅作历史参考**：当前实现是原生 JS + Three.js，没有构建步骤；后续不会据此迁移前端。

第三方素材与许可证：`docs/assets/` 下的脱敏演示图与 `frontend/vendor/three/`（Three.js，MIT）随仓库分发。仓库整体许可证需要所有者确认后再声明。

---

## 依赖

- Python 3.10+
- 运行：FastAPI / Uvicorn / ezdxf / PyYAML / aiofiles / python-multipart / websockets
- 可选：ODA File Converter（仅 DWG → DXF）、matplotlib（视觉审计截图）、Node.js（仅 Vite 开发预览）
- 测试：pytest / httpx（见 `requirements-dev.txt`）

离线安装可先 `pip download -r requirements.txt -d wheelhouse`，再把 `wheelhouse/` 一并拷走。

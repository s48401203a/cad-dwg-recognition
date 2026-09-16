# 发布检查清单（公开仓库）

> **状态说明**：本清单最初写于仓库计划以 **Private** 形式发布时。仓库**现为公开仓库**，
> 因此"必须选择 Private"这一条已不适用；是否调整可见性属于维护者决策，本文不代为决定。
>
> 重要：仓库已被公开抓取过。**把可见性改回 Private 不能撤回已经发生的公开暴露**，
> 也不能清除他人已克隆的副本。历史提交中的内容只能通过改写历史处理，而那属于维护者决策。

## 每次提交前必须确认（与可见性无关）

- [ ] 客户图纸永不入库：任何客户 DWG/DXF、`semantic.json`、客户项目目录都不得进入 Git。
- [ ] 提交列表中不出现 `.dwg` / `.dxf` / `semantic.json` / `*.semantic.json`。
- [ ] 提交列表中不出现 `backend/uploads/`、`backend/projects/`、`backend/projects-archive/`、
      `backend/logs/`、`backups/`、`archives/`、`exports/`、`projects/`。
- [ ] 提交列表中不出现真实项目名称、客户名称、人名、地址、联系方式、真实设备编号截图。
- [ ] 图片只允许提交**由本仓库代码生成**的两张演示图：`docs/assets/demo-scene.png`、
      `docs/assets/demo-export.png`，生成脚本为 `tools_docs/make_demo_screenshots.py`
      （输入是代码生成的合成夹具，可复现）。其它任何截图、图纸或图片一律留在本地。
- [ ] 不要提交来源无法证明的素材。历史提交中的 `docs/assets/demo-sanitized.png` 已因此移除；
      若日后要重新加入任何图片，先确认其生成方式或授权来源。
- [ ] 提交列表中不出现本机绝对路径（类 Unix 的 `/home`、`/Users` 家目录，Windows 的盘符家目录）、
      私有网段地址（RFC1918 三段）、主机名、代理或账号配置。
- [ ] 提交列表中不出现凭据：访问令牌、分享令牌、Cookie、`.env`、私钥、CI 密钥。
- [ ] 运行期状态与产物（`.cad-runtime/`、`.cad-server.json`、`.tmp-verify/`、`node_modules/`、
      `.pytest_cache/`）仍在忽略范围内。

## 本地快速自检

```bash
# 1) 是否有客户图纸 / 解析结果 / 导出产物
git ls-files | grep -iE '\.dwg$|\.dxf$|semantic\.json|^backend/(uploads|projects)|^exports/|^projects/'

# 2) 是否有本机路径与私有网段地址（应只命中回环地址与公共 DNS 这类合法地址）
git grep -nIE '/(Users|home)/[A-Za-z]|[0-9]{2,3}(\.[0-9]{1,3}){3}' | grep -vE '127\.0\.0\.1|0\.0\.0\.0'

# 3) 是否有疑似凭据（按关键字定位，命中后逐条人工判断是否真实凭据）
git grep -niE 'private key|access[_-]?token|client[_-]?secret|passwd|password' | head -40

# 4) 拟提交内容里是否有被忽略目录混入
git status --porcelain | grep -vE '^\?\? '   # 跟踪区改动逐项确认

# 5) 跟踪的图片必须只有本仓库生成的两张演示图
git ls-files | grep -iE '\.(png|jpg|jpeg|gif|webp|bmp|svg)$'

# 6) 第三方许可声明是否随分发保留（Three.js 的 MIT 声明义务）
test -f frontend/vendor/three/LICENSE && echo 'Three.js LICENSE 已随附'
```

命中结果要区分三类，不要一律判为泄露：**真实敏感内容**、**公开信息**
（如 `127.0.0.1`、`8.8.8.8`、公开依赖版本号）、**占位符与合成样例**
（如 `tests/fixtures/` 下由代码生成的 DXF）。

## 首次公开时的操作（已完成）

仓库已通过 `codex/publish-sanitized-root` 分支以脱敏快照形式公开；当前开发分支为
`feat/generic-cad-placement-studio`。若将来需要重新初始化一个干净的公开快照，
流程仍然是：确认 `.gitignore` 生效 → 只挑选通用源码与合成样例 → 提交 → 发布。

## 相关文档

- 公开路线图与项目状态：`README.md` →「项目状态与公开路线图」
- 许可证与公开范围决策项：`RELEASE_READINESS.md`

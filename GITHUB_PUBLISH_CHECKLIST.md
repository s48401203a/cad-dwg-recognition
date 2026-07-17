# GitHub 私有仓库发布检查清单

## 必须确认

- GitHub 仓库必须选择 `Private`。
- 提交列表中不能出现 `.dwg`、`.dxf`、`semantic.json`。
- 提交列表中不能出现 `backend/uploads/`、`backend/projects/`、`backend/logs/`、`backups/`。
- 提交列表中不能出现真实项目名称、客户名称、本机绝对路径、设备真实编号截图。
- 只允许提交 `docs/assets/demo-sanitized.png` 这一张脱敏演示图。

## GitHub Desktop 操作

1. 打开 GitHub Desktop。
2. 选择 `File` -> `Add local repository...`。
3. `Local path` 选择本项目目录。
4. 如果 Desktop 提示创建仓库，确认 `.gitignore` 已存在，不要让 Desktop 覆盖它。
5. 添加后检查 `Changes` 列表。
6. 提交信息填写 `chore: initial private repository`。
7. 点击 `Publish repository`。
8. 发布弹窗中确认勾选 `Keep this code private`，确保仓库是 `Private`。
9. 发布后到 GitHub 网页仓库 `Settings` 中再次确认 `Visibility: Private`。

## 发布前复查

如果 GitHub Desktop 的 `Changes` 里看到任何真实图纸、真实截图、解析结果、项目历史记录或日志，立即取消提交，先检查 `.gitignore`。

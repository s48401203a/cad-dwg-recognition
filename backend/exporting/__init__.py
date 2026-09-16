# -*- coding: utf-8 -*-
"""静态导出子包：把解析结果导出为可离线打开的静态页面。

- `backend/exporting/static_export.py`：自包含的内置实现，用来替代公开分发中缺失的
  `tools/export_static_landing_pages.py`（tools/ 被 .gitignore 排除，公开仓库里不存在）。

刻意不在本文件里 import 子模块：调用方按需 `from exporting.static_export import export_single_project`，
避免 `import exporting` 顺带把 storage / path_policy 一起拉起来。
"""

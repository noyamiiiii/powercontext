# 提测清单

## 表单字段

| 字段 | 内容 |
| --- | --- |
| 代码仓库地址 | <https://github.com/noyamiiiii/powercontext>（Public，fork 自 oceanbase/powercontext） |
| 开发基线 | `2026-competition-ecosystem` @ `d647275c`（官方分支 tip） |
| Branch | `feature/qoder-study-loop` |
| Commit id | `1e1ebbe296564b6cf55100fdde7c2c7efaad2fd2`（含全部代码、文档与 `docs/evidence/` 截图，提测填此 ID） |
| 作品链接 | <https://studyloop-63mjyalrdyh.qoder.zone>（可见范围：任何人都可访问） |
| Qoder 账号 UID | `1816576073851490` |
| Qoder 账号 ID | `01a17cfa-16e0-71da-a415-2923cd667570`（Qoder 设置界面所示，截图 `docs/evidence/05-qoder-account-id.png`） |

平台表单如只有一栏「UID」，先填 `1816576073851490`；两个标识同时留档，避免因字段口径不同而填错。

## 仓库材料

- 完整项目源码：`qoder/studyloop/`
- 可运行界面：`qoder/frontend/`
- Qoder Sites 展示页：`qoder/site/`
- 依赖和运行配置：`qoder/pyproject.toml`（锁定 `powercontext[builtin,server]==1.2.0`）
- 运行说明：`qoder/README.md` 的「运行」章节
- 验证样例：`qoder/README.md` 的「验证样例」章节，附实测预期结果；集成测试在 `qoder/tests/`
- Qoder 开发记录：`qoder/docs/evidence/`（对话与发布截图 + 实测运行日志）

## 提测前检查

已完成：

1. 全新环境按 README 安装并运行成功（`uv sync --extra dev` 46 秒，`uv run studyloop` 起在 8000 端口，`/health` 返回 `{"status":"ok","memory":"PowerContext SQLite"}`）。
2. 完成一次「写入记忆 → 召回计划 → 保存复盘 → 再次召回」的验证，结果记录在 `docs/evidence/2026-10-27-run-log.md`。
3. `uv run pytest` 3 passed；`uv run ruff check .` All checks passed。
4. 通过 Qoder Sites 发布并设为公开访问，未登录浏览器可直接打开。
5. 代码仓库为 Public，评审无需额外授权。
6. 站点文案修正后已重新发布，线上抓取结果与 `qoder/site/index.html` 一致（`uv sync --extra dev`、`memory@1 · artifact_id@revision`）。

提测前还需要：

1. 补最后一张截图：`04-sites-incognito-view.png`（无痕窗口打开作品地址）。若已有的 `04-sites-public-view.png` 就是无痕窗口所截，直接改名即可。`02-run-and-debug.png` 可用 `03-code-change-diff.png` 里的安装报错诊断段作旁证，不强制单独补。
2. 把最终 commit id、作品链接和 Qoder UID 填入测评平台。
3. 评审结束前不要暂停或删除已提交的站点。

赛题不允许只提交设计稿或截图。平台评审时需要实际运行项目，并核对 PowerContext 在计划生成中的作用。

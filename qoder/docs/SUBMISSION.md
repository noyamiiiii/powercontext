# 提测清单

## 表单字段

| 字段 | 内容 |
| --- | --- |
| 代码仓库地址 | `https://github.com/noyamiiiii/powercontext` |
| Branch | `feature/qoder-study-loop` |
| Commit id | 提交本目录后填写该分支的最终 commit |
| 作品链接 | Qoder Sites 发布后的公开网址 |

## 仓库材料

- 完整项目源码：`qoder/studyloop/`
- 可运行界面：`qoder/frontend/`
- Qoder Sites 展示页：`qoder/site/`
- 依赖和运行配置：`qoder/pyproject.toml`
- 运行说明：`qoder/README.md`
- 验证样例：README 与集成测试
- Qoder 开发记录：`qoder/docs/QODER_USAGE.md` 及实际截图

## 提测前检查

1. 在 Qoder 中完成 `QODER_USAGE.md` 的记录要求，确保主要开发过程可核对。
2. 在全新环境中按 README 安装依赖并运行 `studyloop`。
3. 完成一次“写入记忆、召回计划、保存复盘、再次读取”的验证。
4. 运行 `uv run pytest` 和 `uv run ruff check .`。
5. 通过 Qoder Sites 发布 `qoder/site/`，设置公开访问。
6. 用浏览器无痕窗口打开作品网址。
7. 将最终 commit、公开作品链接和 Qoder UID 填入平台。

赛题不允许只提交设计稿或截图。平台评审时需要实际运行项目，并核对 PowerContext 在计划生成中的作用。

# StudyLoop

StudyLoop 是一个有记忆的学习教练。用户输入本次学习目标和可用时间后，应用会从 PowerContext 召回过去的薄弱点、学习偏好和进度，生成一段可以直接执行的复习计划。完成学习后，用户写下的复盘会再次写入 PowerContext，供后续会话使用。

## 问题

学习者经常记得“学过”，却很难在新会话里接上上次的状态：

- 上次在哪一步卡住；
- 哪种复习节奏更适合自己；
- 哪些内容已经掌握，哪些仍需要练习；
- 用了什么方法，结果是否有效。

StudyLoop 把这些对下一次有用的内容保存为长期记忆，而不是要求用户重新翻找聊天记录或笔记。

## PowerContext 的作用

本项目使用 PowerContext 1.2.0 的嵌入式 Runtime，数据保存在本地 SQLite 中。

1. 使用 `ScopeDraft` 创建一个独立学习 Scope。
2. 使用 `runtime.memory.for_scope(scope_id).remember(...)` 写入学习偏好、薄弱点、进度和复盘。
3. 使用 `SearchMemoryRequest(mode="fts")` 根据当前目标召回相关记忆。
4. 将 `MemoryHit` 的计划依据和 citation 一起返回给页面。
5. 将本次复盘作为新的 `outcome` 记忆写入，下一次计划再次读取。

应用不需要模型 API Key。显式记忆写入和 FTS 检索不依赖外部推理服务。

## 运行

需要 Python 3.11 或更高版本（实测环境为 Python 3.12 + uv 0.13.6，Windows）。依赖锁定在 `powercontext[builtin,server]==1.2.0`：1.3 之后的版本移除了 `runtime.memory` / `MemoryApplication`，本项目无法在其上运行，请不要升级这个约束。

推荐用 `uv`（实测 46 秒完成安装）：

```bash
cd qoder
uv sync --extra dev
uv run studyloop
```

或使用虚拟环境。默认 pip 镜像里通常没有 `powercontext`，必须显式指定官方源，且解析依赖需要 20 分钟以上：

```powershell
cd qoder
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]" -i https://pypi.org/simple
studyloop
```

打开 <http://127.0.0.1:8000/app/>。首次启动会在 `qoder/.data/` 写入四条演示学习记忆。如需使用其他数据目录：

```powershell
$env:STUDYLOOP_DATA_DIR = "G:\studyloop-data"
studyloop
```

## 验证样例

下面每一步的“预期结果”都是 2026-10-27 在干净数据目录 + PowerContext 1.2.0 实测得到的，不是设计意图。

1. 首次打开页面，长期记忆列表显示 4 条记录，`kind` 分别是 `learning-preference`、`weak-point`、`progress`、`outcome`。
2. 输入“复习线性代数里的矩阵相似与特征值”，选择 30 分钟并生成计划。预期：标题为“30 分钟复习计划”，4 条步骤，召回摘要显示“已从 PowerContext 召回 2 条相关学习记忆。”
3. 查看“这次用到的记忆”。预期：引用 2 条，分别是薄弱点和历史进度，每条后面的 citation 形如 `memory@1`。
4. 在复盘区输入“可对角化判断还不够熟，下次先做三个反例”并保存。预期：提示写入成功，记忆列表增加为 5 条，新增一条 `outcome`。
5. 再次生成同一目标的计划。预期：召回摘要变为 3 条，刚保存的复盘出现在引用列表里。
6. 点击“复制本次计划”。预期：剪贴板得到 6 行文本 = 计划标题 + 4 条编号步骤 + 召回摘要，页面提示“已复制计划标题、学习步骤和召回摘要。”

两处已知边界，评审如果看到不算故障：

- 该目标下“学习偏好”不会被召回。`make_plan` 把查询拼成 `{目标} 薄弱点 学习偏好 历史进度`，而 1.2.0 的 FTS 准入线是 `max(2, ceil(0.25 × 查询词数))`，目标越长门槛越高，学习偏好那条共享词不够就被过滤。换一个短目标（如“矩阵相似”）时四条种子会全部召回。
- 新复盘会进入引用列表，但不会改写计划步骤。计划文本由 `build_study_plan` 按关键词挑选依据生成，复盘目前只作为可核对的来源展示。

也可以直接检查 API：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod http://127.0.0.1:8000/api/memories
```

`/health` 实测返回 `{"status":"ok","memory":"PowerContext SQLite"}`；`/api/memories` 返回 `scope_id`、`memory_ref` 和每条记忆的 `kind`、`text`、`state`、`citation`，其中 `citation` 含 `artifact_id`、`revision`、`entry_id`、`entry_version_id`，可与 `/api/plan` 返回的引用逐条对上。

## 测试

```bash
cd qoder
uv run pytest
uv run ruff check .
```

实测结果：`3 passed`，`All checks passed!`（ruff 0.17.x，规则见 `pyproject.toml`）。

集成测试会运行真实的嵌入式 PowerContext Runtime，在临时 SQLite 数据库中完成写入、召回和复盘回写。

## 目录

```text
qoder/
├── studyloop/            FastAPI 应用和 PowerContext 集成
├── frontend/             可运行的学习教练界面
├── site/                 Qoder Sites 作品展示页
├── tests/                PowerContext 记忆闭环测试
├── docs/
│   ├── QODER_USAGE.md    Qoder 开发记录要求与复现提示词
│   ├── SUBMISSION.md     提测字段和材料清单
│   └── evidence/         开发过程截图清单与实测运行记录
├── pyproject.toml
└── uv.lock               锁定 powercontext 1.2.0 及全部传递依赖
```

## 隐私与边界

- 演示数据是合成的，不包含真实学生信息。
- 每个应用实例使用独立本地 SQLite 数据目录。
- 项目只保存用户主动写入的学习事实和复盘。
- 项目不提交 `.data/`、凭据或本地虚拟环境。

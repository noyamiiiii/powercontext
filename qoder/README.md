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

需要 Python 3.11 或更高版本。

使用 `uv`：

```bash
cd qoder
uv sync --extra dev
uv run studyloop
```

或使用虚拟环境：

```powershell
cd qoder
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
studyloop
```

打开 <http://127.0.0.1:8000/app/>。首次启动会在 `qoder/.data/` 写入四条演示学习记忆。如需使用其他数据目录：

```powershell
$env:STUDYLOOP_DATA_DIR = "G:\studyloop-data"
studyloop
```

## 验证样例

1. 首次打开页面，长期记忆列表显示 4 条记录。
2. 输入“复习线性代数里的矩阵相似与特征值”，选择 30 分钟并生成计划。
3. 计划应引用“矩阵相似与特征值”的薄弱点、学习偏好和进度。
4. 在复盘区输入“可对角化判断还不够熟，下次先做三个反例”并保存。
5. 刷新页面，长期记忆列表应新增一条 `outcome` 记录。
6. 再次生成与矩阵相似有关的计划，新复盘应参与召回。

也可以直接检查 API：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod http://127.0.0.1:8000/api/memories
```

## 测试

```bash
cd qoder
uv run pytest
uv run ruff check .
```

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
│   └── SUBMISSION.md     提测字段和材料清单
└── pyproject.toml
```

## 隐私与边界

- 演示数据是合成的，不包含真实学生信息。
- 每个应用实例使用独立本地 SQLite 数据目录。
- 项目只保存用户主动写入的学习事实和复盘。
- 项目不提交 `.data/`、凭据或本地虚拟环境。

# 规有所依：SDD 工程上下文模块

针对 [MiniMax × OceanBase 赛题](https://oceanbase.yuque.com/org-wiki-obtech-vh7w9r/hc3pio/qlqnoryzrs7gtqbw)实现。
基于 `oceanbase/powercontext` 的 `2026-competition-ecosystem` 分支，基础提交
`d647275c308e09b7b623f322a26f5c4e85734fb0`，所有作品资产位于 `minimax/`。

**实际完成情况以 `evidence/summary.json` 为准。`complete: false` 表示仍有必做项未完成，不能宣称获得 20 分。**
当前交付的业务修改由 **MiniMax-M3.1-Flash** 根据实际检索出的规格、代码、测试和恢复的任务进度生成，
对应开发记录见 `evidence/minimax-*.json`。评审可以直接验证固定产物，无需提供模型凭据。
重新生成需要有效凭据；校验脚本会核对开发记录与交付源码，缺失或不匹配不能通过真实参与验收项。

## 环境与安装

已验证环境：Ubuntu 24.04 x86_64、Python 3.12.3，可通过 Windows 的 WSL2 运行。
核心版本：`pyseekdb==1.4.0.post1`、嵌入式 `pylibseekdb==1.4.0.post1`、
`powercontext[server]==1.4.0`、`pytest==8.4.2`。完整版本见 `requirements.lock`。
PowerContext 1.4.0 的运行时引用服务端的权限组件，因此安装 `server` extra；本作品无需启动 HTTP 服务。

从仓库根目录进入 `minimax/` 后：

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock
python -m pip check
```

不需要 Docker、独立数据库服务、Embedding API 或额外的本地业务文件。
嵌入式 seekdb 需要 Linux；Windows 请在 WSL2 内安装依赖和执行下述命令。
首次安装需要联网下载公开 Python 包。默认索引位置 `.runtime/seekdb`，
PowerContext 持久化位置 `.runtime/powercontext.db`；均为运行时自动生成，不提交数据库文件。

## 一条命令复现验收

```bash
python scripts/verify.py
```

该命令使用临时工作区，自动进行以下真实操作，并覆盖生成 `evidence/` 下的验收记录：

1. 对 `snapshots/before.py` 执行目标测试，确认失败来自功能断言，并验证原有回归测试通过。
2. 使用相同的测试文件验证交付的 `sample_project/orders.py`，目标与回归测试均须通过。
3. 执行上下文模块集成测试，检查真实 seekdb 查询、来源、过期检测、规格更新和删除后的重新导入。
4. 从空的 PowerContext 状态开始，保存任务记录；退出进程后，在新进程中重新打开数据库，
   将完成事项、待办事项和已有测试结果读入下一份开发上下文。
5. 修改临时规格，重新导入 seekdb，确认输出出现新的 `ORD-005` 内容。

每份测试日志包含命令、退出码、代码 SHA-256 和相同测试文件的 SHA-256。
修改前预期结果为 **13 项目标测试失败、1 项通过，13 项回归测试通过**；
交付实现为 **14 项目标测试通过、13 项回归测试通过**。
`evidence/code.diff` 给出完整业务修改差异；`snapshots/` 保存修改前后快照。
模块测试数量及实际运行结果见日志。不会删除断言、跳过目标测试或修改预期使测试通过。

## 手动调用入口

所有命令均在 `minimax/` 执行。输入为 `project.json` 中的来源清单和 `task.json` 中的任务。
可以通过 `--root`、`--task`、`--runtime` 指定独立工程和存储位置。

```bash
python -m sdd.cli ingest
python -m sdd.cli context --out .runtime/context.json
python -m sdd.cli resume
python -m sdd.cli save --state example-checkpoint.json
# 再次启动一个独立进程，context 的 progress 字段包含刚保存的任务状态
python -m sdd.cli context --out .runtime/resumed.json
```

`ingest` 返回真实写入条目数、移除的过期条目及文件内容摘要。
`context` 返回 `sources`（规格、代码、测试和样例数据的路径、行号、符号、内容摘要及全文）、
`database`（检索命中及扩展来源）和 `progress`（PowerContext 返回的状态及来源标识）。
`resume` 返回最新任务状态，首次返回 `state: null`；`save` 写入不可变的 Source 记录。
`done`、`todo` 为字符串数组，`validations` 为验证记录数组。不同任务使用独立 Scope。

修改 `sample_project/spec.md` 后需再次执行 `ingest`；未重新导入的过期文件会被检测并拒绝使用。
增加或移除来源需更新 `project.json`。索引为全量来源清单，重新导入会删除清单中已经移除的旧条目。

## 真实 MiniMax 开发步骤

在**本机环境**设置 `MINIMAX_API_KEY`、可选 `MINIMAX_BASE_URL` 和 `MINIMAX_MODEL`，
或从 `.env.example` 复制到不受 Git 跟踪的 `.env`，自行填入凭据。
`.env.example` 使用国内官方 Anthropic 兼容接口：
`MINIMAX_BASE_URL=https://api.minimax.cn/anthropic/v1`、`MINIMAX_API_STYLE=anthropic`，
模型为 `MiniMax-M3.1-Flash`。2026-10-26 实测旧的 `MiniMax-M2.7` 已不可用。
也支持 `MINIMAX_API_STYLE=openai` 搭配 `https://api.minimax.io/v1`，
或 `MINIMAX_API_STYLE=native` 搭配 `https://api.minimax.cn/v1`。
须使用适用地区、账户和接口的有效凭据。未提供配置时默认使用国际 OpenAI 兼容接口。

```bash
python scripts/develop.py --env-file .env
python scripts/verify.py
```

`develop.py` 在临时工程中放入真实的修改前源码，导入 seekdb，取得包含规格和测试的上下文，
通过 PowerContext 保存并重新读取开发进度，再把这些资料交给 MiniMax。
MiniMax 返回完整的目标文件，程序限制为只修改 `sample_project/orders.py`，不允许修改测试。
运行相同的业务测试通过后，才把模型产出的文件复制到交付工程。
若模型接口失败或代码测试失败，命令报错，不把未验证的文件覆盖到交付工程。

`evidence/minimax-request.json` 保存任务、上下文和请求；`minimax-response.json` 保存响应标识、
模型、用量和最终代码；`minimax-provenance.json` 保存修改前后摘要；
`minimax-generated-tests.json` 保存该次产物的测试结果。不记录 API 密钥或模型私有推理内容。
固定提交可通过保存的代码与记录验收，评审复现不需要再次生成完全相同的模型输出。

底层也提供 `python -m sdd.cli generate`，直接对当前 `--root` 中的目标文件调用 MiniMax。
日常复现建议使用 `develop.py`，避免将已经实现的文件再次作为修改起点。

## 验证样例与必要来源

任务：实现 `list_orders(..., status=...)` 的精确订单状态筛选，先筛选再分页。
有效值为 `pending`、`paid`、`cancelled`；非法值抛出 `ValueError`。
必须保留原有 id 升序、分页边界、默认值、参数验证及输入不变性。
种子数据包含 6 条订单，其中 3 条为 paid，一条缺少 status。
例如 `status="paid", offset=1, limit=1` 应返回 `id=3` 的订单。

| 必要来源 | 核对内容 |
| --- | --- |
| `sample_project/spec.md` | ORD-001 原行为；ORD-002 新筛选；ORD-003 非法状态；ORD-004 原边界 |
| `sample_project/orders.py::list_orders` | 唯一业务修改目标 |
| `sample_project/tests/test_orders.py` | `target` 新功能与 `regression` 原有行为测试 |
| `sample_project/seed.json` | 初始订单和排序/筛选/分页的预期数据 |

重置样例：`cp snapshots/before.py sample_project/orders.py`，然后重新 `ingest`。
恢复已交付实现：`cp snapshots/after.py sample_project/orders.py`，然后重新 `ingest`。
需要空状态时，为命令传入一个新的 `--runtime` 目录；无需删除现有状态。
`verify.py` 自动使用全新临时工作区，不受用户之前手动调用的状态影响。

## 技术使用记录与限制

| 材料 | 内容 |
| --- | --- |
| `evidence/summary.json` | 六项验收的真实状态 |
| `evidence/database-ingest.json`、`database-query.json` | 实际数据库写入、查询过滤条件、命中 ID、距离 |
| `evidence/context.json`、`context-spec-updated.json` | 真实上下文与规格变更后的输出 |
| `evidence/powercontext-write.log`、`context-resumed.json` | 状态写入、独立进程恢复及上下文复用 |
| `evidence/before-*.log`、`after-*.log`、`module-tests.log` | 相同测试集、版本与退出码 |
| `TECHNICAL.md` | 一页技术说明 |

哈希词向量是无需额外模型的确定性检索表示，不宣称具有神经语义检索能力。
本样例通过命中模块后扩展同模块资料保证规格和测试覆盖，因此上下文大小随模块增长；
大型工程应按依赖关系细分模块并增加预算策略。本 CLI 针对单用户串行运行，不提供并发写入协调。
MiniMax API 的可用性、费用及账户额度由配置的提供方决定；无凭据不能满足真实参与验收项。

样例业务代码和适配模块为本作品原创。PowerContext 和 pyseekdb 作为公开依赖使用，
未复制或修改其 SDK 源码。接口参考：[PowerContext](https://github.com/oceanbase/powercontext)、
[pyseekdb](https://github.com/oceanbase/pyseekdb)、[MiniMax 官方兼容 API](https://platform.minimax.io/docs/api-reference/text-openai-api)。

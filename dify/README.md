# 离谱旅行社

一个跨会话的荒诞故事游戏。玩家输入任何行动，Dify 生成下一幕；PowerContext 保存玩家选择和生成的剧情，新开对话后角色仍会回应之前的决定。

## 为什么好玩

- 没有固定正确路线，任何行动都会改变世界。
- 纸飞机向导阿拐把荒谬事件当作普通公务处理。
- 每次结果都会留下“奇怪规则”，后续剧情必须承担前一轮选择的后果。
- 新开 Dify 对话后，历史选择仍会被召回，形成真正持续的冒险。

## 技术分工

| 组成 | 作用 |
| --- | --- |
| Dify Chatflow | 输入、记忆查询、LLM 剧情生成、记忆写入和最终回复的完整编排 |
| PowerContext | 按 Dify `sys.user_id` 隔离玩家，保存世界设定、角色状态、玩家选择和剧情结果 |
| Dify 模型节点 | 生成场景、规则、记忆回声和下一步建议 |
| 配套 HTTP Bridge | 包装 PowerContext SQLite Runtime，向 Dify 提供稳定的 `recall/remember` 接口 |

PowerContext 不是连接演示。每个 Dify 用户都有独立 Scope；每回合写入 `player-choice` 和 `story-scene` 两类记忆，下一次请求通过 FTS 召回相关历史。

## 运行环境

- Dify 1.18.0 或兼容 DSL `0.6.0` 的版本
- Python 3.11 或更高版本
- 兼容 OpenAI Chat API 的模型；DSL 默认使用 `gpt-4o-mini`
- Docker 自建 Dify 可直接使用 `host.docker.internal:8766` 访问本机 Bridge

如果使用 Dify Cloud，本机地址无法被云端访问。需要用安全的公网隧道暴露 Bridge，并在 DSL 的两个 HTTP Request 节点中替换 URL。不要把临时隧道地址写成永久凭据。

## 启动 Bridge

推荐使用 Docker，Dify 和 Bridge 可以运行在同一台机器上：

```powershell
cd dify
docker compose up -d --build
docker compose ps
```

查看日志：

```powershell
docker compose logs -f memory-bridge
```

停止 Bridge：

```powershell
docker compose down
```

PowerContext 数据保存在 Docker volume `dify_memory-bridge-data` 中。容器对外暴露 `8766`，因此 Docker 版 Dify 可以继续使用 DSL 默认地址 `host.docker.internal:8766`。

如果只想直接运行 Python 服务：

```powershell
cd dify/bridge
uv sync --extra dev
uv run dify-memory-bridge
```

检查服务：

```powershell
Invoke-RestMethod http://127.0.0.1:8766/health
```

默认数据目录是 `dify/bridge/.data/`。可用 `STORY_MEMORY_DATA_DIR` 指定其他目录，用 `STORY_MEMORY_PORT` 修改端口。

## 导入 Dify

1. 在 Dify 中导入 [outlandish-travel-agency.yml](dsl/outlandish-travel-agency.yml)。
2. 如果提示缺少 `langgenius/openai` 插件，按 Dify 的提示安装。
3. 打开“阿拐续写剧情” LLM 节点，将模型重新绑定到当前环境可用的 Chat 模型。不同模型名需要按实际服务修改。
4. 在 Docker 版 Dify 中启动 Bridge 后，确认它可以从 Dify 容器访问：

   ```text
   http://host.docker.internal:8766/health
   ```

5. 检查两个 HTTP Request 节点的 URL：

   - `/v1/recall`
   - `/v1/remember`

6. 发布 Chatflow，打开应用。

Linux Docker 未提供 `host.docker.internal` 时，需要给 Dify API/Worker 容器添加 host-gateway，或把 URL 改成 Dify 能访问到的主机 IP。

如果旧版 DSL 的“返回故事”节点直接显示字面量 `{{#story-llm.text#}}`，请删除该旧应用并重新导入本仓库更新后的 DSL。新版节点 ID 只使用字母、数字和下划线，符合 Dify 运行时的变量解析规则。

## 验证样例

1. 首次输入 `START`。预期得到“午夜旅行社”场景，并显示“新的档案刚刚建立”。
2. 输入 `让一只茶壶宣布竞选市长`。预期茶壶进入剧情并产生一条奇怪规则。
3. 新开一个 Dify 对话，使用同一个用户，输入 `茶壶市长为什么还在追着我`。
4. 预期阿拐在“记忆回声”中引用上一轮的茶壶市长选择。
5. 打开 Dify 工作流运行记录，确认两个 HTTP Request 节点都返回 `200`。
6. 调用下面的接口，核对两类记忆和 citation：

   ```powershell
   Invoke-RestMethod "http://127.0.0.1:8766/v1/memories?user_id=填写-Dify-用户-ID"
   ```

完整步骤和预期现象见 [samples/verification.md](samples/verification.md)。

Dify 预览和工作流运行截图保存在 [docs/evidence/README.md](docs/evidence/README.md)。

启动 Bridge 后也可以直接执行自动验证：

```powershell
dify/bridge/scripts/verify.ps1
```

脚本会验证健康检查、初始记忆、剧情写入和茶壶市长跨回合召回。一次实际运行的结构化结果见 [samples/http-verification.json](samples/http-verification.json)。

## 重置故事

PowerContext 保留审计历史，不做破坏性删除。重置会在当前 Scope 中写入新的章节边界，之后的召回只使用重置后的记忆：

```powershell
$body = @{ user_id = "填写-Dify-用户-ID" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8766/v1/reset -ContentType "application/json" -Body $body
```

## 测试

```powershell
cd dify/bridge
uv run pytest
uv run ruff check .
```

测试会运行真实嵌入式 PowerContext Runtime，覆盖 Scope 隔离、首轮初始化、剧情写入、跨回合召回、幂等写入、重置和 Dify DSL 结构。

## 目录

```text
dify/
├── dsl/
│   └── outlandish-travel-agency.yml
├── bridge/
│   ├── src/story_memory/
│   └── tests/
└── samples/
    └── verification.md
```

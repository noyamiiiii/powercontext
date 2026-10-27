# 验证样例：茶壶市长

## 初始条件

- Bridge 已启动，PowerContext 数据目录为空。
- Dify 已导入 `outlandish-travel-agency.yml`，LLM 节点已绑定可用 Chat 模型。
- 两个 HTTP Request 节点都能访问 Bridge。
- 记录本次 Dify 用户的 `sys.user_id`。

## 第一回合

输入：

```text
START
```

预期：

- 故事发生在午夜营业的离谱旅行社。
- 阿拐介绍自己并给出两个方向。
- “记忆回声”显示新的档案刚刚建立。

## 第二回合

输入：

```text
让一只茶壶宣布竞选市长
```

预期：

- 茶壶成为当前场景角色。
- 阿拐回应玩家的离谱行动，并形成一条可继续利用的“奇怪规则”。
- 工作流执行记录显示 `/v1/remember` 返回 `200`。

## 跨会话验证

新开一个 Dify 对话，保持同一个用户，输入：

```text
茶壶市长为什么还在追着我
```

预期：

- 阿拐在“记忆回声”中引用上一轮的茶壶市长选择。
- 新故事以那次选择为原因继续发展，而不是重新介绍茶壶。

## PowerContext 记录

```powershell
Invoke-RestMethod "http://127.0.0.1:8766/v1/memories?user_id=填写-Dify-用户-ID"
```

应看到：

- `world-setting`
- `character`
- `game-rule`
- 至少一条 `player-choice`
- 至少一条 `story-scene`

每条记录都包含 PowerContext citation 和 revision。

## 重置验证

```powershell
$body = @{ user_id = "填写-Dify-用户-ID" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8766/v1/reset -ContentType "application/json" -Body $body
```

然后输入一个不带茶壶的新故事行动。召回应只包含重置后的剧情状态。

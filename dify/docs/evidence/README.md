# Dify 运行证据

本目录保存“离谱旅行社”Chatflow 的验证截图。

| 顺序 | 文件 | 内容 |
| --- | --- | --- |
| 01 | [01-workflow-preview.png](01-workflow-preview.png) | 完整 Chatflow 节点链路和第一幕预览 |
| 02 | [02-model-binding.png](02-model-binding.png) | “阿拐续写剧情”节点绑定 `deepseek-flash` Chat 模型 |
| 03 | [03-start-run.png](03-start-run.png) | 输入 `START` 后生成完整第一幕 |
| 04 | [04-teapot-run.png](04-teapot-run.png) | 茶壶竞选市长回合及新剧情 |
| 05 | [05-cross-session.png](05-cross-session.png) | 后续提问触发召回 HTTP 节点并继续茶壶市长剧情 |
| 06 | [06-powercontext-memories.png](06-powercontext-memories.png) | 通过 Bridge 查询 PowerContext Scope 和 Memory entries |

截图来自实际 Dify 预览运行。项目不把截图当作代码运行测试的替代品；复现步骤、DSL 和配套源码仍按仓库中的运行说明执行。

# 验证说明

完整验证由 `scripts/verify.py` 调用已发布的真实 Dify Workflow API 完成，具体输出见 `evidence/actual-playthrough.json`。`scripts/collect_evidence.py` 核对节点执行记录及 seekdb 数据；`scripts/verify_guards.py` 额外检查失败及并发行为。

## 实际执行结果（2026-10-27）

- Windows + Ubuntu 24.04 WSL2、Docker Engine 29.1.3、Compose 2.40.3，WSL 内存约 7.6 GiB，模型使用 CPU。
- Dify 1.9.2 实际导入 DSL 0.4.0，状态 `completed`，已发布，八节点全部参与执行。
- 七次真实 Workflow API 请求全部成功，56 个节点执行均为 `succeeded`；单次耗时 0.164–5.685 秒。重复请求未重复生成或推进。
- seekdb 实际版本 `5.7.25-OceanBase seekdb-v1.4.0.0`；六条提交记录，主玩家最终版本 5、三条线索、`reunion` 结局，新玩家无线索、无旧历史。
- Qwen3 模型标签 `qwen3:1.7b`、Ollama 0.12.6、Q4_K_M，实际模型 digest 和运行信息见 `evidence/model.json`。
- 十一项规则/DSL 测试通过；九项真实接口异常与事务保护检查通过，模型停服时玩家状态保持原样。
- 另外在真实 Microsoft Edge 浏览器中，通过页面表单连续完成四回合游戏并获得重逢结局。页面调用 `/play`，再由已发布的 Dify 工作流执行工具链；浏览器操作结果见 `evidence/browser-playthrough.json`，实拍页面见 `evidence/gameplay.png`。
- 页面刷新后从 seekdb 恢复最后结果的检查通过。以上均为实际运行记录，无模拟模型、模板回退或替代 Dify 的执行器。

## 如何重复

按 README 完成初始化及导入，然后执行：

```bash
.venv/bin/python scripts/verify.py
.venv/bin/python scripts/collect_evidence.py
.venv/bin/python -m unittest discover -s tests -v
# 以下检查会短暂停止再启动本作品的 Ollama 容器，请在没有其他玩家操作时执行：
.venv/bin/python scripts/verify_guards.py
```

每轮使用随机新玩家，无需删除历史数据。完整样例按调查铜铃、重复请求、镜子恶作剧、调查镜子、翻看登记簿、安抚并揭晓、独立新玩家的顺序运行。确定性验收比较状态和记忆；模型叙事可能不同，不要求逐字匹配。

## 证据含义

| 文件 | 核对内容 |
| --- | --- |
| `evidence/dify-import.json` | 实际 DSL 导入状态、应用 ID、发布及 API Key 创建结果，不包含 Key |
| `evidence/actual-playthrough.json` | 每次真实 Dify 请求、运行 ID、状态、耗时及完整游戏返回 |
| `evidence/dify-node-executions.json` | 从 Dify 控制台 API 获取的节点类型、标题、状态、耗时 |
| `evidence/seekdb-records.json` | 实际数据库版本、展品数量、玩家状态、已提交回合、历史动作、全文匹配得分 |
| `evidence/summary.json` | 七次完整流程请求的验证结论 |
| `evidence/model.json` | 实际 Ollama 版本、模型规模、量化格式、manifest digest、CPU 加载情况 |
| `evidence/browser-playthrough.json`、`evidence/gameplay.png` | 真实浏览器通过产品表单通关的输出和画面 |
| `evidence/unit-tests.txt` | 十一项规则和工作流契约检查的原始输出 |
| `evidence/guards.json` | 真实工具接口上的未授权、非法输入、并发冲突、重复提交、模型中断验证 |

七次 Dify 请求中有一次是重复请求，因此数据库应只有六个已提交回合：主玩家五回合，新玩家一回合。主玩家最终获得三条证据并进入重逢结局；后续回合上下文能够读出早先的恶作剧。新玩家没有这些历史。

并发检查准备两个同版本回合，真实生成两份叙事后先后提交：第二份应返回 409，避免旧结果覆盖。模型中断检查准备新回合后停止 Ollama，`/narrate` 应返回 503，`/commit` 返回 409，数据库中玩家仍是版本 0、无线索；检查结束自动重启 Ollama。

模型是在本机真实生成文字，没有预置模型回复或故障时的替代叙事。测试不以额外工具框架模拟 Dify；规则单元测试与实际运行证据分别保存。Dify HTTP 节点的模型调用不会计入 Dify 自身的 token 统计，因此该字段为 0 不代表没有推理。

这是一份按赛题可运行性、完整体验、真实技术结合及复现材料要求准备的作品；创意与趣味评分由赛事评审决定，以上验证不等于官方最终得分。

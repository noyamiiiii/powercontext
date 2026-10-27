# Qoder 开发记录

赛题要求项目的主要开发工作必须在 Qoder 中完成，并保留可核对的过程记录。代码本身不能替代这项要求。请在 Qoder 中完成下面的复现记录，并保存截图或录屏。

## 开发过程建议

### 1. 需求拆解

打开 `qoder/` 作为项目目录，在 Qoder 中发送：

```text
分析 qoder/studyloop/coach.py、main.py 和 frontend/ 的现有结构。用你的话列出 StudyLoop 如何通过 PowerContext 完成记忆写入、检索、引用、复盘回写的闭环，并指出需要验证的失败路径。暂时不要修改代码。
```

保存 Qoder 对代码结构和验证方案的回复截图。

### 2. 运行与调试

在 Qoder 中发送：

```text
检查 qoder/pyproject.toml 和 qoder/README.md。告诉我从空环境启动项目、打开页面并完成一条记忆写入与召回的最短步骤。根据实际终端输出修正文档中的问题。
```

保存 Qoder 阅读文件、给出命令和解释报错的截图。

### 3. 功能小改动

在 Qoder 中发送：

```text
保持现有 PowerContext 数据模型不变，为 StudyLoop 增加一个“复制本次计划”按钮。按钮应复制标题、步骤和召回记忆摘要，并提供明确的成功或失败反馈。完成修改后运行 qoder 目录下的测试。
```

保存 Qoder 修改代码的前后 diff、测试命令和测试结果截图。

### 4. Qoder Sites 发布

在 Qoder Sites 中导入 `qoder/site/` 作为展示页，设置可见范围为“任何人都可访问”，发布后使用无痕窗口打开确认。保存：

- Sites 编辑界面截图；
- 发布设置截图；
- 无痕窗口可访问截图；
- Qoder 账号 UID 截图。

## 必需记录

| 记录 | 是否完成 | 存放位置 |
| --- | --- | --- |
| Qoder 账号 UID | 待填写 | 提测表单或 `docs/evidence/` |
| 需求拆解对话截图 | 待保存 | `docs/evidence/` |
| 调试或代码修改截图 | 待保存 | `docs/evidence/` |
| Qoder Sites 发布设置截图 | 待保存 | `docs/evidence/` |
| 公开作品网址 | 待填写 | `docs/SUBMISSION.md` |

截图中的姓名、邮箱和联系方式应打码。不要提交 Qoder 登录凭据。

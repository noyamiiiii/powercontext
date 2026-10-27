# 证据材料清单

赛题要求提交「Qoder 开发记录」：关键开发环节的 Qoder 对话截图或录屏，并附 Qoder 账号 UID。本目录就是这些材料的存放位置。截图需让评审能看出是在 Qoder 里完成的，因此请保留完整窗口（含 Qoder 界面），不要只截回答正文。

## 需要放入的文件

| 文件名 | 内容 | 对应环节 | 状态 |
| --- | --- | --- | --- |
| `01-requirement-analysis.png` | 在 Qoder 里发送 coach.py / main.py / frontend 结构分析请求，以及 Qoder 逐轮读取文件的执行轨迹 | 需求拆解 | 已放入 |
| `01-requirement-analysis-2.png` | Qoder 回复的「一、现有结构」：六个文件的角色与关键行号，以及 coach.py 的三层划分 | 需求拆解 | 已放入 |
| `01-requirement-analysis-3.png` | Qoder 回复的「二、闭环实际怎么走」：启动写入、检索查询组装与 FTS 准入阈值 | 需求拆解 | 已放入 |
| `01-requirement-analysis-4.png` | 需求拆解执行轨迹的后半段：确认当前分支 `src/` 无源码、核对 PyPI 上 `powercontext` 1.2.0 是否真的暴露 `runtime.memory` | 需求拆解 | 已放入 |
| `02-run-and-debug.png` | Qoder 阅读 `pyproject.toml` 和 `README.md`，给出从空环境启动的最短步骤，并解释安装报错 | 运行与调试 | 待补（同环境的安装报错诊断已出现在 `03-code-change-diff.png` 的执行轨迹里，可作旁证） |
| `03-code-change-diff.png` | 「复制本次计划」按钮改动请求与 Qoder 的逐轮变更轨迹（前端三个文件，`coach.py` / `main.py` 未动） | 编码 | 已放入 |
| `03-code-change-tests.png` | Qoder 的改动清单（文件:行号）与 `pytest` `3 passed`、`ruff check .` `All checks passed!` 实跑结果 | 验证 | 已放入 |
| `04-sites-editor.png` | Qoder Sites「我的站点」中 StudyLoop 卡片的编辑界面，显示已发布 | 发布 | 已放入 |
| `04-sites-publish-settings.png` | 站点「设置 → 分享 StudyLoop」弹窗，可见范围为「任何人都可访问」，状态为已发布 | 发布 | 已放入 |
| `04-sites-public-view.png` | 公开地址 <https://studyloop-63mjyalrdyh.qoder.zone> 在浏览器中打开的完整页面（含「Made with Qoder」角标） | 复查 | 已放入 |
| `04-sites-incognito-view.png` | 无痕窗口打开同一地址的截图 | 复查 | 待确认：若 `04-sites-public-view.png` 即为无痕窗口所截，将其改名为本文件即可 |
| `05-qoder-account-id.png` | Qoder 设置中的「账号 ID」`01a17cfa-16e0-71da-a415-2923cd667570` | 提交材料 | 已放入 |

## 打码与禁止出现的内容

- 姓名、邮箱、手机号、头像、组织信息一律打码。
- 不得出现登录凭据、Cookie、Token、API Key。项目本身不需要任何模型 Key，出现即说明配置有误。
- 截图里的终端路径如包含用户名，可一并打码。

已放入的十张截图只包含对话正文、文件名、行号、站点地址、账号 ID 和本地临时目录路径，未出现姓名、邮箱、手机号、头像或任何登录凭据。`03-code-change-tests.png` 里有一条含数字用户名的本地临时路径，属可选打码项。

## 已有材料

- `2026-10-27-run-log.md`：真实运行与验证记录（安装耗时、接口返回、召回条数、剪贴板结果、测试与静态检查结果），可直接作为「指定技术发挥作用的记录」。

# PDF 全文解析与证据页检索

`powercontext.sources.pdf_pages` 提供赛题 `source-03-pdf-retrieval` 要求的四个公共接口。

## 解析与来源

`parse_pdf_document(PDFDocumentInput(document_id=..., content=...))` 接收原始 PDF 字节，使用 pypdf 严格模式逐页提取正文，返回包含空白页的有序元组。页码从 1 开始，表示 PDF 的物理位置。允许空用户密码的权限保护文件；不能解密或不能完整解析时抛出 `ValueError`，不返回部分页面。

每页保留原始输入字节的 SHA-256。`PDF_PAGE_SOURCE_DEFINITION` 的名称为 `pdf-page`、版本为 `1`，产生 CAPTURED Source。来源名称由文档 ID、完整文档摘要和页码的规范元组编码计算，长度固定为 73 字符。文档修订产生新身份，已经保存的旧来源不改变。

标准文本投影保存 `document_id + "\n" + text`；metadata 仅有 `document_id`、`document_sha256` 和 `page_number`。调用方应使用摘要查找原始文件，再按物理页码回查。

## 离线检索

`await search_pdf_pages(memory, question, limit=20)` 接收已打开的 scoped Memory。通过公开 `memory.search` 执行 FTS 检索，并通过 `memory.list` 读取同一作用域当前有效的页面条目。在这些真实条目上计算 BM25、财务术语扩展和报表标题匹配；对需要多张报表的查询保留各相关概念的候选。文档 ID 中可识别的公司和年份作为选择范围的依据，不维护公司、问题或页码清单。

结果使用 Memory 条目自带的精确 citation，按页来源去重，最多返回 `limit` 条。空问题、非正上限和空 Memory 返回空元组。全程不调用模型、在线服务，不读取预解析文件、标注或判题资产，不写旁路索引。

复杂度随当前作用域页面正文总长度增长；每次查询读取并排序本作用域的页面，适用于本题约千页的规模。

## 安装与验证

普通解析使用 `powercontext[pdf]`；真实 Runtime 检索还需要 `powercontext[builtin]`。比赛以组织方的固定环境为准，已在 Linux x86_64、Python 3.12.3、pypdf 6.19.0 上验证。

仓库根目录执行：

```bash
make -C competition install
make -C competition test-pdf
```

补充回归测试为 `tests/test_pdf_pages.py`，覆盖全文及数字、空白页、非法输入、后页损坏、空密码、长 Unicode ID、修订身份和真实 Runtime 重启回查。产品实现不依赖这些测试。

公开自测只验证接口及公开行为，不提供质量标注，不能证明隐藏集 Recall@20、证据词项召回率或整页 F1 已达到正式评分门槛。

# Edge Course Lens

浏览器本地 embedding + seekdb 混合检索的迷你课程知识库。

完整流程：

```text
导入文本文档
  → 浏览器 Worker 生成文档向量
  → Node 服务写入 seekdb
  → refresh_index
  → 浏览器生成查询向量
  → seekdb DBMS_HYBRID_SEARCH + RRF
  → 展示原文、来源与耗时
```

详细设计、量化数据与官方来源见 [TECHNICAL_REPORT.md](TECHNICAL_REPORT.md)。

## 环境

- Node.js 22+
- Docker Desktop 或其他可运行 Linux 容器的 Docker 环境
- Chrome 或 Edge 最新版
- 首次加载模型时需要访问 Hugging Face；也可以预先通过浏览器缓存模型

## 启动 seekdb

```powershell
cd stepfun
npm run db:start
```

该命令使用官方 `oceanbase/seekdb:1.4.0` 镜像，并在 `127.0.0.1:2881` 暴露 MySQL 协议。数据保存在 Docker volume `stepfun_seekdb-data`。

确认容器：

```powershell
docker compose ps
```

## 启动应用

```powershell
npm install
npm run dev
```

打开 <http://127.0.0.1:5173>。

也可以运行生产构建：

```powershell
npm run build
npm start
```

生产入口为 <http://127.0.0.1:8787>。`npm install` 会读取 `.npmrc` 中的 `legacy-peer-deps=true`，原因是 seekdb 当前 npm 元数据把可选默认 embedding 适配器声明为 peer；本项目不需要该适配器，因为向量由浏览器生成。

## 验证样例

1. 在左侧点击 `+`，创建“端侧 RAG 课程”知识库。
2. 上传 [samples/course-notes.md](samples/course-notes.md)。
3. 观察右侧指标出现文档向量化、写入与索引刷新耗时。
4. 查询 `浏览器没有 GPU 支持时使用什么后端`。
5. 结果中应出现 WASM 回退相关段落，并显示 `source`、`chunk` 和 seekdb 返回的排序分数。
6. 再导入一次相同文件，collection 文本块数量不会重复增长，验证 upsert。
7. 切换知识库或新建第二个知识库，检索结果应只来自当前 collection。

## 测试

```powershell
npm run typecheck
npm test
npm run build
```

启动 seekdb 后执行真实数据库验收：

```powershell
npm run test:seekdb
```

模型量化质量评测：

```powershell
npm run benchmark:models
```

## 配置

复制 `.env.example` 中需要的值到启动环境。Vite 前端不需要 API Key；服务端配置包括：

| 变量 | 默认值 | 用途 |
| --- | --- | --- |
| `PORT` | `8787` | Node API 和静态站点端口 |
| `SEEKDB_MODE` | `server` | `server` 或 Linux 下的 `embedded` |
| `SEEKDB_HOST` | `127.0.0.1` | seekdb server 地址 |
| `SEEKDB_PORT` | `2881` | MySQL 协议端口 |
| `SEEKDB_USER` | `root` | 默认用户 |
| `SEEKDB_PASSWORD` | 空 | Docker 示例的默认密码 |
| `SEEKDB_DATABASE` | `test` | seekdb 数据库名 |
| `SEEKDB_DATA_DIR` | `./.seekdb` | catalog 与嵌入式数据目录 |

使用嵌入式模式时，显式设置 `SEEKDB_MODE=embedded`。Windows 与 macOS 的稳定部署方式仍是 Docker server；嵌入式模式适配 Linux 环境。

## 目录

```text
stepfun/
├── src/
│   ├── workers/embedding.worker.ts
│   ├── components/
│   └── lib/
├── server/
│   ├── index.ts
│   └── store.ts
├── scripts/
│   ├── model-benchmark.ts
│   └── seekdb-smoke.ts
├── benchmarks/
├── samples/course-notes.md
├── docker-compose.yml
└── TECHNICAL_REPORT.md
```

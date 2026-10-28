import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, ShieldCheck } from "lucide-react";

import { ImportPanel } from "./components/ImportPanel";
import { PerformancePanel } from "./components/PerformancePanel";
import { SearchPanel } from "./components/SearchPanel";
import { Sidebar } from "./components/Sidebar";
import { StatusPill } from "./components/StatusPill";
import {
  createCollection,
  deleteCollection,
  listCollections,
  searchDocuments,
  upsertDocuments,
} from "./lib/api";
import { EmbeddingClient } from "./lib/embedding-client";
import { prepareDocuments, type TextSource } from "./lib/text";
import type {
  EmbeddingBackend,
  KnowledgeBase,
  KnowledgeDocument,
  MetricEntry,
  SearchResult,
} from "./types";

type Operation = "idle" | "import" | "search" | "collection";

function dtypeLabel(dtype: EmbeddingBackend["dtype"]): string {
  return dtype === "q8" ? "INT8" : "FP16";
}

export default function App() {
  const [embeddingClient] = useState(() => new EmbeddingClient());
  const [bases, setBases] = useState<KnowledgeBase[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [backend, setBackend] = useState<EmbeddingBackend | null>(null);
  const [operation, setOperation] = useState<Operation>("idle");
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState(0);
  const [progressLabel, setProgressLabel] = useState("正在加载端侧模型");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [metrics, setMetrics] = useState<MetricEntry[]>([]);

  const activeBase = useMemo(
    () => bases.find((base) => base.id === activeId) ?? null,
    [activeId, bases],
  );

  useEffect(() => {
    let cancelled = false;
    void listCollections()
      .then((collections) => {
        if (cancelled) {
          return;
        }
        setBases(collections);
        setActiveId((current) => current ?? collections[0]?.id ?? null);
      })
      .catch((reason: Error) => setError(reason.message));

    const startedAt = performance.now();
    void embeddingClient
      .load((update) => {
        setProgress(update.progress);
        setProgressLabel(update.message);
      })
      .then((loaded) => {
        setBackend(loaded.backend);
        setProgress(100);
        setProgressLabel(
          `${loaded.backend.device.toUpperCase()} / ${dtypeLabel(loaded.backend.dtype)} 已就绪`,
        );
        addMetric(
          "模型加载",
          loaded.loadMs,
          `${loaded.backend.device}/${dtypeLabel(loaded.backend.dtype)}`,
        );
      })
      .catch((reason: Error) => {
        setError(reason.message);
        setProgressLabel("模型加载失败");
      });

    return () => {
      cancelled = true;
      embeddingClient.terminate();
    };
  }, [embeddingClient]);

  function addMetric(label: string, durationMs: number, detail: string) {
    setMetrics((current) => [
      ...current,
      {
        id: crypto.randomUUID(),
        label,
        durationMs,
        detail,
        recordedAt: new Date().toISOString(),
      },
    ]);
  }

  async function refreshCollections(selectId?: string) {
    const collections = await listCollections();
    setBases(collections);
    if (selectId) {
      setActiveId(selectId);
    } else if (!collections.some((base) => base.id === activeId)) {
      setActiveId(collections[0]?.id ?? null);
    }
  }

  async function handleCreate(name: string) {
    setOperation("collection");
    setError(null);
    try {
      const created = await createCollection(name);
      await refreshCollections(created.id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "创建知识库失败");
    } finally {
      setOperation("idle");
    }
  }

  async function handleDelete(id: string) {
    setOperation("collection");
    setError(null);
    try {
      await deleteCollection(id);
      await refreshCollections();
      setResults([]);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "删除知识库失败");
    } finally {
      setOperation("idle");
    }
  }

  async function handleImport(sources: TextSource[], batchSize: number) {
    if (!activeId) {
      return;
    }
    const e2eStartedAt = performance.now();
    setOperation("import");
    setError(null);
    setProgress(0);
    setProgressLabel("正在切分文本");
    try {
      const prepared = prepareDocuments(sources);
      if (prepared.length === 0) {
        throw new Error("没有找到可导入的文本");
      }
      if (prepared.length > 128) {
        throw new Error("单次最多导入 128 个文本块，请分批导入");
      }
      setProgressLabel(`准备向量化 ${prepared.length} 个文本块`);
      const embedded = await embeddingClient.embedDocuments(
        prepared.map((document) => document.text),
        batchSize,
        (update) => {
          setProgress(update.progress);
          setProgressLabel(update.message);
        },
      );
      addMetric(
        "文档向量化",
        embedded.embeddingMs,
        `${prepared.length} 块 · batch ${batchSize} · ${backend?.device ?? "local"}`,
      );

      const documents: KnowledgeDocument[] = prepared.map((document, index) => ({
        ...document,
        embedding: embedded.embeddings[index],
      }));
      setProgress(96);
      setProgressLabel("写入 seekdb 并刷新索引");
      const database = await upsertDocuments(activeId, documents);
      addMetric(
        "写入 + 刷新索引",
        database.databaseMs,
        `${documents.length} 块`,
      );
      addMetric(
        "端到端导入",
        performance.now() - e2eStartedAt,
        `${documents.length} 块`,
      );
      setProgress(100);
      setProgressLabel(`已写入 ${documents.length} 个文本块`);
      await refreshCollections(activeId);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "导入失败");
    } finally {
      setOperation("idle");
    }
  }

  async function handleSearch(query: string, limit: number) {
    if (!activeId) {
      return;
    }
    const e2eStartedAt = performance.now();
    setOperation("search");
    setError(null);
    try {
      const embedded = await embeddingClient.embedQuery(query);
      addMetric(
        "查询向量化",
        embedded.embeddingMs,
        `${backend?.device ?? "local"} / ${backend ? dtypeLabel(backend.dtype) : "local"}`,
      );
      const response = await searchDocuments(
        activeId,
        query,
        embedded.embeddings[0],
        limit,
      );
      setResults(response.results);
      addMetric(
        "seekdb 混合检索",
        response.databaseMs,
        `Top ${limit} · ${response.fusion}`,
      );
      addMetric(
        "端到端查询",
        performance.now() - e2eStartedAt,
        `${response.results.length} 条结果`,
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "检索失败");
    } finally {
      setOperation("idle");
    }
  }

  const busy = operation !== "idle";
  const disabledReason = !activeBase
    ? "先创建一个知识库"
    : activeBase.count === 0
      ? "当前知识库还没有可检索内容"
      : null;

  return (
    <div className="app-shell">
      <Sidebar
        bases={bases}
        activeId={activeId}
        busy={busy}
        onSelect={(id) => {
          setActiveId(id);
          setResults([]);
        }}
        onCreate={handleCreate}
        onDelete={handleDelete}
      />

      <main className="workspace">
        <header className="workspace__header">
          <div>
            <span className="eyebrow">ON-DEVICE · HYBRID SEARCH</span>
            <h1>{activeBase?.name ?? "端侧课程知识库"}</h1>
            <p>
              {activeBase
                ? `${activeBase.count} 个文本块已写入 seekdb。查询与文档向量均由当前浏览器生成。`
                : "创建一个知识库，开始浏览器本地向量化和 seekdb 混合检索。"}
            </p>
          </div>
          <div className="status-cluster">
            <StatusPill
              kind="embedding"
              label={backend ? backend.device.toUpperCase() : "模型加载中"}
              detail={
                backend
                  ? `${dtypeLabel(backend.dtype)} · 512d`
                  : progressLabel
              }
              loading={!backend}
            />
            <StatusPill kind="seekdb" label="seekdb 1.4.0" detail="Server mode" />
          </div>
        </header>

        {error ? (
          <div className="alert" role="alert">
            <AlertTriangle size={18} />
            <span>{error}</span>
            <button type="button" onClick={() => setError(null)} aria-label="关闭错误提示">
              ×
            </button>
          </div>
        ) : null}

        <div className="content-grid">
          <div className="content-main">
            <ImportPanel
              activeCollection={Boolean(activeBase)}
              busy={busy}
              backend={backend}
              progress={operation === "import" ? progress : 0}
              progressLabel={progressLabel}
              onImport={handleImport}
            />
            <SearchPanel
              activeCollection={Boolean(activeBase)}
              busy={busy}
              disabledReason={disabledReason}
              results={results}
              onSearch={handleSearch}
            />
          </div>
          <PerformancePanel
            backend={backend}
            metrics={metrics}
            progress={progress}
            progressLabel={progressLabel}
          />
        </div>

        <footer className="local-proof">
          <ShieldCheck size={16} />
          <span>
            向量计算只在浏览器 Worker 中执行。服务端接收向量、文本和元数据，seekdb 完成存储、索引刷新与 RRF 混合检索。
          </span>
        </footer>
      </main>
    </div>
  );
}

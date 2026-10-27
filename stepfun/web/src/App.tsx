import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import BenchmarkPanel from "./components/BenchmarkPanel";
import ImportPanel, { type IngestSource } from "./components/ImportPanel";
import SearchPanel from "./components/SearchPanel";
import StatusBar from "./components/StatusBar";
import { ApiError, api, type ApiConfig, type KbListEntry, type KbStats, type SearchResponse } from "./api/client";
import { chunkText, makeDocId } from "./lib/chunk";
import { createEmbedder, type Device, type Embedder, type EmbedProgress } from "./lib/embedder";
import { EVAL_CASES, SAMPLE_DOCS } from "../../shared/sampleCorpus";
import type {
  BenchmarkRow,
  BenchmarkSummary,
  IngestProgress,
  IngestSummary,
  QueryTimings,
} from "./uiTypes";

type SearchMode = "hybrid" | "vector" | "fulltext";

const MEDIAN = (values: number[]): number => {
  if (values.length === 0) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 0 ? (sorted[mid - 1] + sorted[mid]) / 2 : sorted[mid];
};

/** Binary-relevance nDCG@k with a single relevant grade. */
function ndcgAtK(rankedIds: string[], relevant: string[], k: number): number {
  const rel = new Set(relevant);
  let dcg = 0;
  for (let i = 0; i < Math.min(k, rankedIds.length); i += 1) {
    if (rel.has(rankedIds[i])) dcg += 1 / Math.log2(i + 2);
  }
  let idcg = 0;
  for (let i = 0; i < Math.min(k, relevant.length); i += 1) idcg += 1 / Math.log2(i + 2);
  return idcg === 0 ? 0 : dcg / idcg;
}

function recallAtK(rankedIds: string[], relevant: string[], k: number): number {
  if (relevant.length === 0) return 0;
  const top = new Set(rankedIds.slice(0, k));
  return relevant.filter((id) => top.has(id)).length / relevant.length;
}

function errorText(err: unknown): string {
  if (err instanceof ApiError) {
    return `${err.message}${err.requestId ? `（requestId: ${err.requestId}）` : ""}`;
  }
  return err instanceof Error ? err.message : String(err);
}

export default function App() {
  const [config, setConfig] = useState<ApiConfig | null>(null);
  const [kbs, setKbs] = useState<KbListEntry[]>([]);
  const [kb, setKb] = useState("default");
  const [stats, setStats] = useState<KbStats | null>(null);

  const [embedder, setEmbedder] = useState<Embedder | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadMessage, setLoadMessage] = useState("");
  const [loadProgress, setLoadProgress] = useState<number | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [batchSize, setBatchSize] = useState(8);
  const [chunkSize, setChunkSize] = useState(400);

  const [ingestProgress, setIngestProgress] = useState<IngestProgress>({
    running: false,
    stage: "",
    done: 0,
    total: 0,
  });
  const [ingestSummary, setIngestSummary] = useState<IngestSummary | null>(null);
  const [ingestError, setIngestError] = useState<string | null>(null);

  const [mode, setMode] = useState<SearchMode>("hybrid");
  const [topK, setTopK] = useState(5);
  const [queryRunning, setQueryRunning] = useState(false);
  const [searchResult, setSearchResult] = useState<SearchResponse | null>(null);
  const [timings, setTimings] = useState<QueryTimings | null>(null);
  const [searchError, setSearchError] = useState<string | null>(null);

  const [benchRunning, setBenchRunning] = useState(false);
  const [benchProgress, setBenchProgress] = useState({ done: 0, total: 0 });
  const [benchSummary, setBenchSummary] = useState<BenchmarkSummary | null>(null);
  const [baseline, setBaseline] = useState<BenchmarkSummary | null>(null);
  const [baselineRunning, setBaselineRunning] = useState(false);
  const [benchError, setBenchError] = useState<string | null>(null);

  const embedderRef = useRef<Embedder | null>(null);
  embedderRef.current = embedder;
  /** Guards against React StrictMode's double effect invocation loading the model twice. */
  const initializationStarted = useRef(false);

  const crossOriginIsolated = typeof window !== "undefined" && window.crossOriginIsolated;

  /* ---------------------------------------------------------------- bootstrap */

  const refreshKbList = useCallback(async (current?: string) => {
    const res = await api.listKbs();
    setKbs(res.collections);
    if (res.collections.length === 0 && current) {
      setKbs([{ name: `kb_${current}`, kb: current, count: 0 }]);
    }
  }, []);

  const refreshStats = useCallback(async (target: string) => {
    try {
      setStats(await api.stats(target));
    } catch (err) {
      setSearchError(errorText(err));
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const meta = await api.meta();
        if (cancelled) return;
        setConfig(meta.config);
        setKb(meta.config.defaultKb);
        setStats(meta.defaultKbStats);
        await refreshKbList(meta.config.defaultKb);
      } catch (err) {
        if (!cancelled) setLoadError(errorText(err));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [refreshKbList]);

  /* ---------------------------------------------------------------- embedder */

  const initEmbedder = useCallback(
    async (modelId: string, force?: Device) => {
      setLoading(true);
      setLoadError(null);
      setLoadProgress(0);
      setLoadMessage("准备加载模型…");
      try {
        const previous = embedderRef.current;
        if (previous) {
          await previous.dispose().catch(() => undefined);
          setEmbedder(null);
          embedderRef.current = null;
        }
        const next = await createEmbedder({
          modelId,
          pooling: "cls",
          forceDevice: force,
          onProgress: (p: EmbedProgress) => {
            setLoadMessage(p.message ?? (p.file ? `加载 ${p.file}` : p.stage));
            if (typeof p.progress === "number") setLoadProgress(Math.min(99, p.progress));
          },
        });
        setEmbedder(next);
        embedderRef.current = next;
        setLoadProgress(100);
      } catch (err) {
        setLoadError(errorText(err));
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  useEffect(() => {
    if (!config || initializationStarted.current) return;
    initializationStarted.current = true;
    void initEmbedder(config.embeddingModel);
  }, [config, initEmbedder]);

  /* ------------------------------------------------------------------ ingest */

  const handleIngest = useCallback(
    async (source: IngestSource) => {
      const active = embedderRef.current;
      const cfg = config;
      if (!active || !cfg) return;

      setIngestError(null);
      setIngestSummary(null);
      try {
        let docs: { id: string; text: string; metadata: Record<string, string> }[] = [];
        if (source.kind === "sample") {
          docs = SAMPLE_DOCS.map((doc) => ({
            id: doc.id,
            text: doc.text,
            metadata: { title: doc.title, source: "sample" },
          }));
        } else {
          const raw =
            source.kind === "paste"
              ? source.text
              : await source.file.text();
          const chunks = chunkText(raw, { maxChars: chunkSize });
          if (chunks.length === 0) throw new Error("没有从输入中解析出有效文本");
          const prefix = source.kind === "paste" ? "paste" : source.file.name.replace(/\.[^.]+$/, "").slice(0, 24);
          const stamp = Date.now().toString(36);
          docs = chunks.map((text, index) => ({
            id: `${prefix}-${stamp}-${makeDocId("c", index).split("-")[1]}`,
            text,
            metadata: { source: source.kind === "paste" ? "paste" : "file" },
          }));
        }

        setIngestProgress({ running: true, stage: `向量化 0/${docs.length}`, done: 0, total: docs.length });

        const embedStart = performance.now();
        const { vectors, ms } = await active.embedDocuments(
          docs.map((d) => d.text),
          batchSize,
          (done, total) =>
            setIngestProgress({
              running: true,
              stage: `本地向量化 ${done}/${total}`,
              done,
              total,
            }),
        );
        const embedMs = performance.now() - embedStart;
        if (vectors.length !== docs.length) {
          throw new Error(`向量数量 (${vectors.length}) 与片段数量 (${docs.length}) 不一致`);
        }

        setIngestProgress({ running: true, stage: "写入 seekdb 并刷新索引…", done: docs.length, total: docs.length });
        const uploadStart = performance.now();
        const res = await api.ingest(kb, docs.map((doc, i) => ({
          id: doc.id,
          text: doc.text,
          embedding: vectors[i],
          metadata: doc.metadata,
        })));
        const uploadMs = performance.now() - uploadStart;

        setIngestSummary({
          chunks: docs.length,
          embedMs,
          uploadMs,
          writeMs: res.timings.writeMs,
          refreshMs: res.timings.refreshMs,
          inserted: res.inserted,
          skipped: res.skipped,
          collectionTotal: res.total,
          throughput: ms > 0 ? (docs.length / ms) * 1000 : 0,
          backendLabel: active.backend.label,
          batchSize,
        });
        await Promise.all([refreshStats(kb), refreshKbList(kb)]);
      } catch (err) {
        setIngestError(errorText(err));
      } finally {
        setIngestProgress({ running: false, stage: "", done: 0, total: 0 });
      }
    },
    [batchSize, chunkSize, config, kb, refreshKbList, refreshStats],
  );

  /* ------------------------------------------------------------------ search */

  const runQuery = useCallback(
    async (query: string): Promise<{ embedMs: number; dbMs: number; ids: string[]; totalMs: number }> => {
      const active = embedderRef.current;
      const cfg = config;
      if (!active || !cfg) throw new Error("推理后端尚未就绪");

      const embedStart = performance.now();
      const { vector, ms: embedMs } = await active.embedQuery(cfg.queryInstruction + query);
      const embedEnd = performance.now();
      const res = await api.search(kb, {
        queryEmbedding: vector,
        queryText: query,
        topK: mode === "hybrid" ? Math.max(topK, 10) : topK,
        mode,
      });
      const end = performance.now();

      setSearchResult(res);
      setTimings({
        embedMs,
        networkMs: end - embedEnd,
        dbMs: res.dbMs,
        refreshMs: res.refreshMs,
        totalMs: end - embedStart,
        backendLabel: active.backend.label,
      });
      return { embedMs, dbMs: res.dbMs, ids: res.results.map((r) => r.id), totalMs: end - embedStart };
    },
    [config, kb, mode, topK],
  );

  const handleSearch = useCallback(
    async (query: string) => {
      setQueryRunning(true);
      setSearchError(null);
      try {
        await runQuery(query);
      } catch (err) {
        setSearchError(errorText(err));
        setSearchResult(null);
        setTimings(null);
      } finally {
        setQueryRunning(false);
      }
    },
    [runQuery],
  );

  /* --------------------------------------------------------------- benchmark */

  const evaluate = useCallback(
    async (target: Embedder, label: string): Promise<BenchmarkSummary> => {
      const cfg = config;
      if (!cfg) throw new Error("配置尚未加载");
      const rows: BenchmarkRow[] = [];
      const embedSamples: number[] = [];
      const dbSamples: number[] = [];
      const totalSamples: number[] = [];
      const recalls5: number[] = [];
      const recalls10: number[] = [];
      const ndcgs: number[] = [];
      const rr: number[] = [];

      setBenchProgress({ done: 0, total: EVAL_CASES.length });
      for (let i = 0; i < EVAL_CASES.length; i += 1) {
        const testCase = EVAL_CASES[i];
        const start = performance.now();
        const { vector, ms: embedMs } = await target.embedQuery(cfg.queryInstruction + testCase.query);
        const res = await api.search(kb, {
          queryEmbedding: vector,
          queryText: testCase.query,
          topK: 10,
          mode: "hybrid",
        });
        const totalMs = performance.now() - start;
        const ids = res.results.map((r) => r.id);
        const rankIndex = ids.findIndex((id) => testCase.relevant.includes(id));
        const rank = rankIndex >= 0 ? rankIndex + 1 : null;

        rows.push({
          query: testCase.query,
          rank,
          hit: rank !== null,
          embedMs,
          dbMs: res.dbMs,
          totalMs,
          topIds: ids.slice(0, 5),
        });
        embedSamples.push(embedMs);
        dbSamples.push(res.dbMs);
        totalSamples.push(totalMs);
        recalls5.push(recallAtK(ids, testCase.relevant, 5));
        recalls10.push(recallAtK(ids, testCase.relevant, 10));
        ndcgs.push(ndcgAtK(ids, testCase.relevant, 10));
        rr.push(rank !== null ? 1 / rank : 0);
        setBenchProgress({ done: i + 1, total: EVAL_CASES.length });
      }

      const mean = (values: number[]) => values.reduce((a, b) => a + b, 0) / Math.max(1, values.length);

      return {
        label,
        backendLabel: target.backend.label,
        dtype: target.backend.dtype,
        cases: EVAL_CASES.length,
        recall5: mean(recalls5),
        recall10: mean(recalls10),
        ndcg10: mean(ndcgs),
        mrr: mean(rr),
        embedMedianMs: MEDIAN(embedSamples),
        dbMedianMs: MEDIAN(dbSamples),
        totalMedianMs: MEDIAN(totalSamples),
        rows,
      };
    },
    [config, kb],
  );

  const handleRunBenchmark = useCallback(async () => {
    const active = embedderRef.current;
    if (!active) return;
    setBenchRunning(true);
    setBenchError(null);
    try {
      setBenchSummary(await evaluate(active, "当前后端"));
    } catch (err) {
      setBenchError(errorText(err));
    } finally {
      setBenchRunning(false);
      setBenchProgress({ done: 0, total: 0 });
    }
  }, [evaluate]);

  const handleRunBaseline = useCallback(async () => {
    const cfg = config;
    if (!cfg) return;
    setBaselineRunning(true);
    setBenchError(null);
    try {
      // Load a second, FP32 pipeline to isolate the effect of quantization on
      // retrieval quality. Metrics are computed on the same corpus, same
      // evaluation set, same seekdb collection -- only precision differs.
      const fp32 = await createEmbedder({
        modelId: cfg.embeddingModel,
        pooling: "cls",
        forceDtype: "fp32",
        onProgress: (p) => setLoadMessage(p.message ?? ""),
      });
      try {
        setBaseline(await evaluate(fp32, "FP32 基线"));
      } finally {
        await fp32.dispose().catch(() => undefined);
      }
    } catch (err) {
      setBenchError(errorText(err));
    } finally {
      setBaselineRunning(false);
      setBenchProgress({ done: 0, total: 0 });
    }
  }, [config, evaluate]);

  const handleCopy = useCallback(() => {
    if (!benchSummary) return;
    const payload = { current: benchSummary, baseline };
    void navigator.clipboard.writeText(JSON.stringify(payload, null, 2));
  }, [baseline, benchSummary]);

  /* ------------------------------------------------------------------- kb ops */

  const handleCreateKb = useCallback(
    async (name: string) => {
      try {
        await api.createKb(name);
        setKb(name);
        await Promise.all([refreshKbList(name), refreshStats(name)]);
        setSearchResult(null);
        setTimings(null);
      } catch (err) {
        setIngestError(errorText(err));
      }
    },
    [refreshKbList, refreshStats],
  );

  const handleKbChange = useCallback(
    (next: string) => {
      setKb(next);
      setSearchResult(null);
      setTimings(null);
      setBenchSummary(null);
      setBaseline(null);
      void refreshStats(next);
    },
    [refreshStats],
  );

  const handleReset = useCallback(async () => {
    try {
      await api.resetKb(kb);
      await Promise.all([refreshStats(kb), refreshKbList(kb)]);
      setSearchResult(null);
      setBenchSummary(null);
      setBaseline(null);
    } catch (err) {
      setIngestError(errorText(err));
    }
  }, [kb, refreshKbList, refreshStats]);

  const handleRefresh = useCallback(async () => {
    try {
      await api.refresh(kb);
      await refreshStats(kb);
    } catch (err) {
      setIngestError(errorText(err));
    }
  }, [kb, refreshStats]);

  const wasmThreads = embedder?.wasmThreads ?? 0;

  const kbOptions = useMemo(
    () => (kbs.some((entry) => entry.kb === kb) ? kbs : [{ name: kb, kb, count: stats?.count ?? 0 }, ...kbs]),
    [kb, kbs, stats],
  );

  return (
    <div className="app">
      <StatusBar
        config={config}
        stats={stats}
        backend={embedder?.backend ?? null}
        loading={loading}
        loadMessage={loadMessage}
        loadProgress={loadProgress}
        loadError={loadError}
        wasmThreads={wasmThreads}
        crossOriginIsolated={crossOriginIsolated}
        onReload={(force) => {
          if (config) void initEmbedder(config.embeddingModel, force);
        }}
      />

      <div className="grid">
        <div className="col">
          <ImportPanel
            ready={!!embedder}
            kb={kb}
            kbs={kbOptions}
            stats={stats}
            batchSize={batchSize}
            chunkSize={chunkSize}
            progress={ingestProgress}
            summary={ingestSummary}
            error={ingestError}
            onBatchSizeChange={setBatchSize}
            onChunkSizeChange={setChunkSize}
            onKbChange={handleKbChange}
            onCreateKb={(name) => void handleCreateKb(name)}
            onReset={() => void handleReset()}
            onRefresh={() => void handleRefresh()}
            onIngest={(source) => void handleIngest(source)}
          />
          <BenchmarkPanel
            ready={!!embedder}
            running={benchRunning}
            progress={benchProgress}
            summary={benchSummary}
            baseline={baseline}
            baselineRunning={baselineRunning}
            error={benchError}
            onRun={() => void handleRunBenchmark()}
            onRunBaseline={() => void handleRunBaseline()}
            onCopy={handleCopy}
          />
        </div>

        <div className="col">
          <SearchPanel
            ready={!!embedder}
            running={queryRunning}
            topK={topK}
            mode={mode}
            result={searchResult}
            timings={timings}
            error={searchError}
            onTopKChange={setTopK}
            onModeChange={setMode}
            onSearch={(query) => void handleSearch(query)}
          />
        </div>
      </div>
    </div>
  );
}

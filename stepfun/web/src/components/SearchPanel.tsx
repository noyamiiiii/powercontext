import { useState } from "react";
import type { SearchResponse } from "../api/client";
import { EVAL_CASES } from "../../../shared/sampleCorpus";
import type { QueryTimings } from "../uiTypes";

type Mode = "hybrid" | "vector" | "fulltext";

interface Props {
  ready: boolean;
  running: boolean;
  topK: number;
  mode: Mode;
  result: SearchResponse | null;
  timings: QueryTimings | null;
  error: string | null;
  onTopKChange: (n: number) => void;
  onModeChange: (m: Mode) => void;
  onSearch: (query: string) => void;
}

const MODE_LABEL: Record<Mode, string> = {
  hybrid: "混合检索 (向量 + 全文, RRF)",
  vector: "纯向量检索",
  fulltext: "纯全文检索",
};

const SCORE_LABEL: Record<SearchResponse["scoreKind"], string> = {
  rrf: "RRF 融合分数",
  "cosine-similarity": "余弦相似度",
  keyword: "关键词匹配",
};

export default function SearchPanel(props: Props) {
  const [query, setQuery] = useState("写入后为什么查询不到新文档");
  const { result, timings } = props;

  const run = () => {
    const q = query.trim();
    if (q) props.onSearch(q);
  };

  return (
    <section className="card">
      <h2>
        检索
        <span className="pills">
          <span className="pill mono">
            topK <b>{props.topK}</b>
          </span>
          {result && (
            <span className="pill mono">
              命中 <b>{result.total}</b>
            </span>
          )}
        </span>
      </h2>
      <p className="hint">
        查询向量在浏览器本地计算；混合检索由 seekdb 的 <code className="inline">hybridSearch</code> 完成，
        RRF 融合在库内进行。
      </p>

      <div className="field">
        <input
          value={query}
          placeholder="输入自然语言问题…"
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") run();
          }}
          disabled={props.running}
        />
      </div>

      <div className="field inline">
        <div>
          <label>检索模式</label>
          <select
            value={props.mode}
            onChange={(e) => props.onModeChange(e.target.value as Mode)}
            disabled={props.running}
          >
            {(Object.keys(MODE_LABEL) as Mode[]).map((m) => (
              <option key={m} value={m}>
                {MODE_LABEL[m]}
              </option>
            ))}
          </select>
        </div>
        <div style={{ maxWidth: 110 }}>
          <label>topK</label>
          <input
            type="number"
            min={1}
            max={50}
            value={props.topK}
            onChange={(e) => props.onTopKChange(Number(e.target.value))}
            disabled={props.running}
          />
        </div>
        <div style={{ flex: "0 0 auto", alignSelf: "flex-end" }}>
          <button className="primary" onClick={run} disabled={!props.ready || props.running || !query.trim()}>
            {props.running ? "检索中…" : "检索"}
          </button>
        </div>
      </div>

      <div className="row tight" style={{ flexWrap: "wrap" }}>
        {EVAL_CASES.slice(0, 4).map((c) => (
          <button key={c.query} className="ghost" onClick={() => setQuery(c.query)} disabled={props.running}>
            {c.query}
          </button>
        ))}
      </div>

      {timings && (
        <>
          <div className="metrics" style={{ marginTop: 12 }}>
            <div className="metric">
              <span className="k">查询向量化</span>
              <span className="v">
                {timings.embedMs.toFixed(1)}
                <small>ms</small>
              </span>
            </div>
            <div className="metric">
              <span className="k">seekdb 检索</span>
              <span className="v">
                {timings.dbMs.toFixed(2)}
                <small>ms</small>
              </span>
            </div>
            <div className="metric">
              <span className="k">索引刷新</span>
              <span className="v">
                {timings.refreshMs.toFixed(2)}
                <small>ms</small>
              </span>
            </div>
            <div className="metric">
              <span className="k">端到端</span>
              <span className="v">
                {timings.totalMs.toFixed(0)}
                <small>ms</small>
              </span>
            </div>
          </div>
          <div className="progress-label" style={{ marginTop: 6 }}>
            <span>
              后端 {timings.backendLabel} · 端到端 = 查询向量化 + 网络往返 + seekdb 检索
            </span>
            <span>网络 {timings.networkMs.toFixed(0)}ms</span>
          </div>
        </>
      )}

      {props.error && <div className="note error">{props.error}</div>}

      {result && result.results.length > 0 && (
        <>
          <div className="progress-label" style={{ marginTop: 12 }}>
            <span>
              {MODE_LABEL[result.mode]} · 分数口径：{SCORE_LABEL[result.scoreKind]}
            </span>
            <span>{result.total} 条</span>
          </div>
          <div className="results">
            {result.results.map((hit, index) => (
              <article className="hit" key={`${hit.id}-${index}`}>
                <div className="hit-head">
                  <span className="rank">#{index + 1}</span>
                  <span className="hit-id">{hit.id}</span>
                  <span className="hit-score">
                    {hit.score === null ? "—" : hit.score.toFixed(4)}
                  </span>
                </div>
                <p className="hit-text">{hit.text ?? "(无正文)"}</p>
                {hit.metadata && Object.keys(hit.metadata).length > 0 && (
                  <div className="hit-meta">
                    {Object.entries(hit.metadata)
                      .map(([k, v]) => `${k}=${String(v)}`)
                      .join("  ")}
                  </div>
                )}
              </article>
            ))}
          </div>
        </>
      )}

      {result && result.results.length === 0 && (
        <div className="empty" style={{ marginTop: 12 }}>
          没有命中结果。请先导入语料，或换一个关键词。
        </div>
      )}

      {!result && !props.error && (
        <div className="empty" style={{ marginTop: 12 }}>
          输入查询开始检索。首次检索包含 ONNX session 预热后的稳定状态计时。
        </div>
      )}
    </section>
  );
}

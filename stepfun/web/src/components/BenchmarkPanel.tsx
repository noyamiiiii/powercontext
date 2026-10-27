import type { BenchmarkSummary } from "../uiTypes";

interface Props {
  ready: boolean;
  running: boolean;
  progress: { done: number; total: number };
  summary: BenchmarkSummary | null;
  baseline: BenchmarkSummary | null;
  baselineRunning: boolean;
  error: string | null;
  onRun: () => void;
  onRunBaseline: () => void;
  onCopy: () => void;
}

function pct(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

function delta(current: number, base: number): string {
  const diff = (current - base) * 100;
  if (Math.abs(diff) < 0.05) return "0.0";
  return `${diff > 0 ? "+" : ""}${diff.toFixed(1)}`;
}

export default function BenchmarkPanel(props: Props) {
  const { summary, baseline } = props;
  const percent = props.progress.total > 0 ? (props.progress.done / props.progress.total) * 100 : 0;

  return (
    <section className="card">
      <h2>
        检索质量与性能评测
        <span className="pills">
          <span className="pill mono">评测集 12 条</span>
        </span>
      </h2>
      <p className="hint">
        用固定评测集跑完整「查询向量化 → seekdb 混合检索」链路，输出 Recall@5 / Recall@10 / nDCG@10 / MRR
        与各阶段耗时中位数。FP32 基线用于对比量化后的质量变化。
      </p>

      <div className="row">
        <button className="primary" onClick={props.onRun} disabled={!props.ready || props.running || props.baselineRunning}>
          {props.running ? "评测中…" : "运行评测（当前后端）"}
        </button>
        <button onClick={props.onRunBaseline} disabled={!props.ready || props.running || props.baselineRunning}>
          {props.baselineRunning ? "加载 FP32 基线…" : "对比 FP32 基线"}
        </button>
        {summary && (
          <button className="ghost" onClick={props.onCopy}>
            复制 JSON 结果
          </button>
        )}
      </div>

      {(props.running || props.baselineRunning) && (
        <>
          <div className="progress">
            <span style={{ width: `${percent}%` }} />
          </div>
          <div className="progress-label">
            <span>{props.baselineRunning ? "加载 FP32 权重并评测" : "逐条检索评测集中…"}</span>
            <span>
              {props.progress.done}/{props.progress.total}
            </span>
          </div>
        </>
      )}

      {props.error && <div className="note error">{props.error}</div>}

      {summary && (
        <>
          <div className="metrics" style={{ marginTop: 12 }}>
            <div className="metric">
              <span className="k">Recall@5</span>
              <span className="v">{pct(summary.recall5)}</span>
            </div>
            <div className="metric">
              <span className="k">Recall@10</span>
              <span className="v">{pct(summary.recall10)}</span>
            </div>
            <div className="metric">
              <span className="k">nDCG@10</span>
              <span className="v">{summary.ndcg10.toFixed(3)}</span>
            </div>
            <div className="metric">
              <span className="k">MRR</span>
              <span className="v">{summary.mrr.toFixed(3)}</span>
            </div>
            <div className="metric">
              <span className="k">向量化中位数</span>
              <span className="v">
                {summary.embedMedianMs.toFixed(1)}
                <small>ms</small>
              </span>
            </div>
            <div className="metric">
              <span className="k">检索中位数</span>
              <span className="v">
                {summary.dbMedianMs.toFixed(2)}
                <small>ms</small>
              </span>
            </div>
            <div className="metric">
              <span className="k">端到端中位数</span>
              <span className="v">
                {summary.totalMedianMs.toFixed(0)}
                <small>ms</small>
              </span>
            </div>
          </div>

          <div className="progress-label" style={{ marginTop: 8 }}>
            <span>
              当前配置：{summary.backendLabel} · {summary.dtype} · {summary.cases} 条查询
            </span>
          </div>

          {baseline && (
            <>
              <table className="data">
                <thead>
                  <tr>
                    <th>指标</th>
                    <th className="num">{baseline.dtype.toUpperCase()} 基线</th>
                    <th className="num">{summary.dtype.toUpperCase()} + {summary.backendLabel}</th>
                    <th className="num">变化 (pp)</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td>Recall@5</td>
                    <td className="num">{pct(baseline.recall5)}</td>
                    <td className="num">{pct(summary.recall5)}</td>
                    <td className="num">{delta(summary.recall5, baseline.recall5)}</td>
                  </tr>
                  <tr>
                    <td>Recall@10</td>
                    <td className="num">{pct(baseline.recall10)}</td>
                    <td className="num">{pct(summary.recall10)}</td>
                    <td className="num">{delta(summary.recall10, baseline.recall10)}</td>
                  </tr>
                  <tr>
                    <td>nDCG@10</td>
                    <td className="num">{baseline.ndcg10.toFixed(3)}</td>
                    <td className="num">{summary.ndcg10.toFixed(3)}</td>
                    <td className="num">
                      {((summary.ndcg10 - baseline.ndcg10) * 100 > 0 ? "+" : "") +
                        ((summary.ndcg10 - baseline.ndcg10) * 100).toFixed(1)}
                    </td>
                  </tr>
                  <tr>
                    <td>MRR</td>
                    <td className="num">{baseline.mrr.toFixed(3)}</td>
                    <td className="num">{summary.mrr.toFixed(3)}</td>
                    <td className="num">
                      {((summary.mrr - baseline.mrr) * 100 > 0 ? "+" : "") +
                        ((summary.mrr - baseline.mrr) * 100).toFixed(1)}
                    </td>
                  </tr>
                  <tr>
                    <td>向量化中位数 (ms)</td>
                    <td className="num">{baseline.embedMedianMs.toFixed(1)}</td>
                    <td className="num">{summary.embedMedianMs.toFixed(1)}</td>
                    <td className="num">
                      {(summary.embedMedianMs - baseline.embedMedianMs > 0 ? "+" : "") +
                        (summary.embedMedianMs - baseline.embedMedianMs).toFixed(1)}
                    </td>
                  </tr>
                </tbody>
              </table>
              <div className="note info">
                FP32 基线与量化版本使用同一份评测集、同一台设备、同一个 seekdb 集合，仅精度不同，
                因此差值可直接归因于量化。
              </div>
            </>
          )}

          <table className="data">
            <thead>
              <tr>
                <th>#</th>
                <th>查询</th>
                <th className="num">命中位次</th>
                <th className="num">向量化</th>
                <th className="num">检索</th>
              </tr>
            </thead>
            <tbody>
              {summary.rows.map((row, index) => (
                <tr key={row.query}>
                  <td>{index + 1}</td>
                  <td style={{ whiteSpace: "normal", maxWidth: 320 }}>{row.query}</td>
                  <td className="num" style={{ color: row.hit ? "var(--ok)" : "var(--danger)" }}>
                    {row.rank === null ? "未命中" : `#${row.rank}`}
                  </td>
                  <td className="num">{row.embedMs.toFixed(1)}ms</td>
                  <td className="num">{row.dbMs.toFixed(2)}ms</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      {!summary && !props.running && (
        <div className="empty" style={{ marginTop: 12 }}>
          先导入示例语料，再运行评测即可得到可复现的质量与延迟数据。
        </div>
      )}
    </section>
  );
}

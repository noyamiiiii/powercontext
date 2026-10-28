import { Download, Gauge } from "lucide-react";

import type { EmbeddingBackend, MetricEntry } from "../types";
import { formatBytes } from "../lib/text";

const MODEL_SIZES = {
  fp32: 94_806_745,
  fp16: 47_424_911,
  q8: 23_942_210,
};

interface PerformancePanelProps {
  backend: EmbeddingBackend | null;
  metrics: MetricEntry[];
  progressLabel: string;
  progress: number;
}

function formatMs(value: number): string {
  return value >= 1000 ? `${(value / 1000).toFixed(2)} s` : `${value.toFixed(0)} ms`;
}

export function PerformancePanel({
  backend,
  metrics,
  progressLabel,
  progress,
}: PerformancePanelProps) {
  function exportMetrics() {
    const blob = new Blob(
      [
        JSON.stringify(
          {
            backend,
            modelSizes: MODEL_SIZES,
            metrics,
            exportedAt: new Date().toISOString(),
          },
          null,
          2,
        ),
      ],
      { type: "application/json" },
    );
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "edge-course-lens-metrics.json";
    anchor.click();
    URL.revokeObjectURL(url);
  }

  const activeDtype = backend?.dtype ?? "q8";
  const modelBytes = MODEL_SIZES[activeDtype];

  return (
    <aside className="metrics-panel" aria-labelledby="metrics-title">
      <div className="metrics-panel__heading">
        <div>
          <Gauge size={17} />
          <h2 id="metrics-title">运行指标</h2>
        </div>
        <button
          className="icon-button"
          type="button"
          onClick={exportMetrics}
          title="导出指标 JSON"
          aria-label="导出指标 JSON"
        >
          <Download size={15} />
        </button>
      </div>

      <dl className="spec-list">
        <div>
          <dt>后端</dt>
          <dd>{backend ? backend.device.toUpperCase() : "等待检测"}</dd>
        </div>
        <div>
          <dt>精度</dt>
          <dd>
            {backend ? (backend.dtype === "q8" ? "INT8" : "FP16") : "INT8 / FP16"}
          </dd>
        </div>
        <div>
          <dt>模型权重</dt>
          <dd>{backend ? formatBytes(modelBytes) : "-"}</dd>
        </div>
        <div>
          <dt>向量维度</dt>
          <dd>{backend?.dimension ?? 512}</dd>
        </div>
      </dl>

      {backend?.fallbackReason ? (
        <p className="fallback-note">{backend.fallbackReason}</p>
      ) : null}

      {progress > 0 && progress < 100 ? (
        <div className="metrics-progress">
          <div className="progress-track">
            <span style={{ width: `${progress}%` }} />
          </div>
          <small>{progressLabel}</small>
        </div>
      ) : null}

      <div className="metric-list">
        {metrics.length === 0 ? (
          <p className="metrics-empty">加载模型或执行一次检索后，这里会显示实测耗时。</p>
        ) : (
          metrics
            .slice()
            .reverse()
            .map((metric) => (
              <div className="metric-row" key={metric.id}>
                <div>
                  <strong>{metric.label}</strong>
                  <small>{metric.detail}</small>
                </div>
                <b>{formatMs(metric.durationMs)}</b>
              </div>
            ))
        )}
      </div>

      <div className="size-comparison">
        <span>FP32 基线</span>
        <b>{formatBytes(MODEL_SIZES.fp32)}</b>
        <span>FP16</span>
        <b>{formatBytes(MODEL_SIZES.fp16)}</b>
        <span>INT8</span>
        <b>{formatBytes(MODEL_SIZES.q8)}</b>
      </div>
    </aside>
  );
}

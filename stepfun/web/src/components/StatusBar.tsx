import type { ApiConfig, KbStats } from "../api/client";
import type { BackendInfo, Device } from "../lib/embedder";

interface Props {
  config: ApiConfig | null;
  stats: KbStats | null;
  backend: BackendInfo | null;
  loading: boolean;
  loadMessage: string;
  loadProgress: number | null;
  loadError: string | null;
  wasmThreads: number;
  crossOriginIsolated: boolean;
  onReload: (force?: Device) => void;
}

export default function StatusBar({
  config,
  stats,
  backend,
  loading,
  loadMessage,
  loadProgress,
  loadError,
  wasmThreads,
  crossOriginIsolated,
  onReload,
}: Props) {
  return (
    <>
      <header className="header">
        <div>
          <h1>seekdb × 阶跃星辰 · 端侧向量化迷你知识库</h1>
          <p className="sub">
            浏览器本地向量化（Transformers.js / ONNX Runtime Web）→ 写入 seekdb（嵌入式）→ 向量 + 全文混合检索（RRF 在库内融合）
          </p>
        </div>
        <div className="pills">
          {backend ? (
            <span className={`pill ${backend.degraded ? "warn" : "ok"}`} title={backend.reason ?? ""}>
              <span className="dot" />
              <b>{backend.label}</b>
            </span>
          ) : (
            <span className="pill warn">
              <span className="dot" />
              <b>{loading ? "推理后端加载中" : "推理后端未就绪"}</b>
            </span>
          )}
          {config && (
            <span className="pill mono">
              模型 <b>{config.embeddingModel.split("/").pop()}</b>
            </span>
          )}
          {config && (
            <span className="pill mono">
              dim <b>{config.embeddingDim}</b>
            </span>
          )}
          {stats && (
            <span className="pill mono">
              片段 <b>{stats.count}</b>
            </span>
          )}
          {backend?.device === "wasm" && (
            <span className="pill mono">
              线程 <b>{wasmThreads}</b>
              {!crossOriginIsolated && " (单线程)"}
            </span>
          )}
          <button className="ghost" onClick={() => onReload()} disabled={loading}>
            重新加载
          </button>
          <button
            className="ghost"
            onClick={() => onReload(backend?.device === "wasm" ? "webgpu" : "wasm")}
            disabled={loading}
            title="手动切换推理后端，用于验证降级路径"
          >
            {backend?.device === "wasm" ? "试 WebGPU" : "强制 WASM"}
          </button>
        </div>
      </header>

      {loading && (
        <div className="card" style={{ marginBottom: 16 }}>
          <div className="progress-label" style={{ marginBottom: 8 }}>
            <span>
              <span className="spin" />
              {loadMessage || "正在加载模型…"}
            </span>
            {loadProgress !== null && <span>{Math.round(loadProgress)}%</span>}
          </div>
          <div className="progress">
            <span style={{ width: `${loadProgress ?? 8}%` }} />
          </div>
        </div>
      )}

      {loadError && !loading && <div className="note error">{loadError}</div>}

      {backend && !loading && (
        <div className={`note ${backend.degraded ? "warn" : "info"}`} style={{ marginBottom: 16 }}>
          {backend.degraded ? (
            <>
              当前使用 <b>WASM</b> 后端（{backend.dtype.toUpperCase()} 权重）：{backend.reason}。
              核心检索流程仍可正常运行，只是推理速度低于 GPU 路径。
            </>
          ) : (
            <>
              当前使用 <b>WebGPU</b> 后端（FP16 权重），模型加载耗时{" "}
              <code className="inline">{Math.round(backend.loadMs ?? 0)}ms</code>。若设备不支持 WebGPU，
              应用会自动降级到 WASM 并在界面上提示。
            </>
          )}
        </div>
      )}
    </>
  );
}

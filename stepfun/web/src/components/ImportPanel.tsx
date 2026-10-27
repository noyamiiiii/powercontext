import { useRef, useState } from "react";
import type { KbListEntry, KbStats } from "../api/client";
import { SAMPLE_DOCS } from "../../../shared/sampleCorpus";
import type { IngestProgress, IngestSummary } from "../uiTypes";

export type IngestSource =
  | { kind: "sample" }
  | { kind: "paste"; text: string }
  | { kind: "file"; file: File };

interface Props {
  ready: boolean;
  kb: string;
  kbs: KbListEntry[];
  stats: KbStats | null;
  batchSize: number;
  chunkSize: number;
  progress: IngestProgress;
  summary: IngestSummary | null;
  error: string | null;
  onBatchSizeChange: (n: number) => void;
  onChunkSizeChange: (n: number) => void;
  onKbChange: (kb: string) => void;
  onCreateKb: (name: string) => void;
  onReset: () => void;
  onRefresh: () => void;
  onIngest: (source: IngestSource) => void;
}

const TABS = [
  { id: "sample", label: `示例语料 (${SAMPLE_DOCS.length})` },
  { id: "paste", label: "粘贴文本" },
  { id: "file", label: "上传文件" },
] as const;

type TabId = (typeof TABS)[number]["id"];

export default function ImportPanel(props: Props) {
  const [tab, setTab] = useState<TabId>("sample");
  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [newKb, setNewKb] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);
  const { progress, summary } = props;
  const busy = progress.running;

  const percent = progress.total > 0 ? (progress.done / progress.total) * 100 : 0;

  const submit = () => {
    if (tab === "sample") props.onIngest({ kind: "sample" });
    else if (tab === "paste" && text.trim()) props.onIngest({ kind: "paste", text });
    else if (tab === "file" && file) props.onIngest({ kind: "file", file });
  };

  const canSubmit =
    props.ready &&
    !busy &&
    ((tab === "sample") || (tab === "paste" && text.trim().length > 0) || (tab === "file" && !!file));

  return (
    <section className="card">
      <h2>
        知识库
        <span className="pills">
          <span className="pill mono">
            集合 <b>{props.stats?.collection ?? "—"}</b>
          </span>
        </span>
      </h2>
      <p className="hint">
        每个知识库对应 seekdb 里的一个集合，向量与全文索引同集合建立。
      </p>

      <div className="field inline">
        <div>
          <label>当前知识库</label>
          <select value={props.kb} onChange={(e) => props.onKbChange(e.target.value)} disabled={busy}>
            {props.kbs.length === 0 && <option value={props.kb}>{props.kb}</option>}
            {props.kbs.map((entry) => (
              <option key={entry.kb} value={entry.kb}>
                {entry.kb} ({entry.count >= 0 ? entry.count : "?"})
              </option>
            ))}
          </select>
        </div>
        <div>
          <label>新建 / 切换</label>
          <div className="row tight" style={{ flexWrap: "nowrap" }}>
            <input
              value={newKb}
              placeholder="kb 名称，如 notes"
              onChange={(e) => setNewKb(e.target.value.trim().toLowerCase())}
              onKeyDown={(e) => {
                if (e.key === "Enter" && newKb) {
                  props.onCreateKb(newKb);
                  setNewKb("");
                }
              }}
              disabled={busy}
            />
            <button
              onClick={() => {
                if (!newKb) return;
                props.onCreateKb(newKb);
                setNewKb("");
              }}
              disabled={busy || !/^[a-z0-9][a-z0-9-]{0,47}$/.test(newKb)}
            >
              新建
            </button>
          </div>
        </div>
      </div>

      <div className="row" style={{ marginBottom: 4 }}>
        <span className="pill mono">
          片段 <b>{props.stats?.count ?? 0}</b>
        </span>
        <span className="pill mono">
          dim <b>{props.stats?.dimension ?? "—"}</b>
        </span>
        <span className="pill mono">
          距离 <b>{props.stats?.distance ?? "—"}</b>
        </span>
        {props.stats?.pendingRefresh && <span className="pill warn">索引待刷新</span>}
        <button className="ghost" onClick={props.onRefresh} disabled={busy}>
          手动刷新索引
        </button>
        <button className="ghost" onClick={props.onReset} disabled={busy || (props.stats?.count ?? 0) === 0}>
          清空
        </button>
      </div>

      <div className="tabs" style={{ marginTop: 14 }}>
        {TABS.map((t) => (
          <button
            key={t.id}
            className={tab === t.id ? "active" : ""}
            onClick={() => setTab(t.id)}
            disabled={busy}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "sample" && (
        <div className="note info" style={{ marginTop: 0 }}>
          内置 {SAMPLE_DOCS.length} 段中文技术片段（seekdb / 端侧推理 / 检索评测），一键完成「切片 →
          本地向量化 → 写入 seekdb → 索引刷新」，可直接配合下方评测集复现 Recall@K。
        </div>
      )}

      {tab === "paste" && (
        <div className="field">
          <label>文本内容（按空行切分，超长段落按句子再切）</label>
          <textarea
            value={text}
            placeholder="粘贴任意文档内容…"
            onChange={(e) => setText(e.target.value)}
            disabled={busy}
          />
          <div className="progress-label">
            <span>{text.length} 字符</span>
          </div>
        </div>
      )}

      {tab === "file" && (
        <div className="field">
          <label>选择 .txt / .md 文件</label>
          <input
            ref={fileInput}
            type="file"
            accept=".txt,.md,.markdown,text/plain,text/markdown"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            disabled={busy}
            style={{ padding: 6 }}
          />
          {file && (
            <div className="progress-label" style={{ marginTop: 6 }}>
              <span>{file.name}</span>
              <span>{(file.size / 1024).toFixed(1)} KB</span>
            </div>
          )}
        </div>
      )}

      <div className="field inline">
        <div>
          <label>切片长度（字符）</label>
          <input
            type="number"
            min={80}
            max={2000}
            step={20}
            value={props.chunkSize}
            onChange={(e) => props.onChunkSizeChange(Number(e.target.value))}
            disabled={busy}
          />
        </div>
        <div>
          <label>批大小 batchSize（性能优化项）</label>
          <input
            type="number"
            min={1}
            max={64}
            value={props.batchSize}
            onChange={(e) => props.onBatchSizeChange(Number(e.target.value))}
            disabled={busy}
          />
        </div>
      </div>

      <div className="row">
        <button className="primary" onClick={submit} disabled={!canSubmit}>
          {busy ? "处理中…" : "导入并向量化"}
        </button>
        {!props.ready && <span className="pill warn">等待推理后端就绪</span>}
      </div>

      {busy && (
        <>
          <div className="progress">
            <span style={{ width: `${percent}%` }} />
          </div>
          <div className="progress-label">
            <span>{progress.stage}</span>
            <span>
              {progress.done}/{progress.total}
            </span>
          </div>
        </>
      )}

      {summary && !busy && (
        <>
          <div className="note ok">
            已写入 <b>{summary.inserted}</b> 个片段（集合共 {summary.collectionTotal}），
            向量化 {summary.embedMs.toFixed(0)}ms · 写入 {summary.writeMs.toFixed(0)}ms · 索引刷新{" "}
            {summary.refreshMs.toFixed(0)}ms
          </div>
          <div className="metrics" style={{ marginTop: 10 }}>
            <div className="metric">
              <span className="k">吞吐</span>
              <span className="v">
                {summary.throughput.toFixed(1)}
                <small>片段/秒</small>
              </span>
            </div>
            <div className="metric">
              <span className="k">向量化</span>
              <span className="v">
                {summary.embedMs.toFixed(0)}
                <small>ms</small>
              </span>
            </div>
            <div className="metric">
              <span className="k">写入 seekdb</span>
              <span className="v">
                {summary.writeMs.toFixed(0)}
                <small>ms</small>
              </span>
            </div>
            <div className="metric">
              <span className="k">索引刷新</span>
              <span className="v">
                {summary.refreshMs.toFixed(0)}
                <small>ms</small>
              </span>
            </div>
            <div className="metric">
              <span className="k">batch</span>
              <span className="v">{summary.batchSize}</span>
            </div>
            <div className="metric">
              <span className="k">后端</span>
              <span className="v" style={{ fontSize: 12 }}>
                {summary.backendLabel}
              </span>
            </div>
          </div>
        </>
      )}

      {props.error && <div className="note error">{props.error}</div>}
    </section>
  );
}

import { useRef, useState } from "react";
import { FilePlus2, Upload } from "lucide-react";

import type { EmbeddingBackend } from "../types";
import type { TextSource } from "../lib/text";

interface ImportPanelProps {
  activeCollection: boolean;
  busy: boolean;
  backend: EmbeddingBackend | null;
  progress: number;
  progressLabel: string;
  onImport: (sources: TextSource[], batchSize: number) => Promise<void>;
}

export function ImportPanel({
  activeCollection,
  busy,
  backend,
  progress,
  progressLabel,
  onImport,
}: ImportPanelProps) {
  const [text, setText] = useState("");
  const [batchSize, setBatchSize] = useState(8);
  const fileInput = useRef<HTMLInputElement>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const sources: TextSource[] = [];
    if (text.trim()) {
      sources.push({ name: "pasted-text.txt", text });
    }
    const files = fileInput.current?.files;
    if (files) {
      for (const file of Array.from(files)) {
        sources.push({ name: file.name, text: await file.text() });
      }
    }
    if (sources.length === 0) {
      return;
    }
    await onImport(sources, batchSize);
    setText("");
    if (fileInput.current) {
      fileInput.current.value = "";
    }
  }

  return (
    <section className="panel import-panel" aria-labelledby="import-title">
      <div className="panel__heading">
        <div>
          <span className="eyebrow">LOCAL INGESTION</span>
          <h2 id="import-title">导入课程材料</h2>
        </div>
        <span className="panel__step">01</span>
      </div>
      <p className="panel__intro">
        文本先由浏览器生成向量，再写入 seekdb。模型文件可以从网络下载，但推理计算只发生在这台设备。
      </p>

      <form className="import-form" onSubmit={submit}>
        <label className="file-drop" htmlFor="course-files">
          <Upload size={22} aria-hidden="true" />
          <span>选择 .txt 或 .md 文件</span>
          <small>可多选，也可以直接在下方粘贴内容</small>
          <input
            ref={fileInput}
            id="course-files"
            type="file"
            accept=".txt,.md,text/plain,text/markdown"
            multiple
            disabled={!activeCollection || busy}
          />
        </label>

        <label className="field-label" htmlFor="paste-text">
          粘贴课程内容
        </label>
        <textarea
          id="paste-text"
          rows={8}
          value={text}
          disabled={!activeCollection || busy}
          onChange={(event) => setText(event.target.value)}
          placeholder={"把课程笔记粘贴到这里。\n\n空行会作为文本块边界，长段落会自动切分。"}
        />

        <div className="form-row">
          <label className="field-label" htmlFor="batch-size">
            Embedding 批大小
          </label>
          <select
            id="batch-size"
            value={batchSize}
            onChange={(event) => setBatchSize(Number(event.target.value))}
            disabled={busy}
          >
            {[1, 4, 8, 16].map((size) => (
              <option value={size} key={size}>
                {size}
              </option>
            ))}
          </select>
        </div>

        {progress > 0 && progress < 100 ? (
          <div className="progress-block" role="status" aria-live="polite">
            <div className="progress-track">
              <span style={{ width: `${progress}%` }} />
            </div>
            <small>{progressLabel}</small>
          </div>
        ) : null}

        <button
          className="button button--primary"
          type="submit"
          disabled={
            !activeCollection ||
            busy ||
            !backend ||
            (!text.trim() && !(fileInput.current?.files?.length ?? 0))
          }
        >
          <FilePlus2 size={17} />
          {busy ? "正在本地向量化…" : "向量化并写入 seekdb"}
        </button>
      </form>
    </section>
  );
}

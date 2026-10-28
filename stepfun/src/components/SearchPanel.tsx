import { useState } from "react";
import { Search } from "lucide-react";

import type { SearchResult } from "../types";

interface SearchPanelProps {
  activeCollection: boolean;
  busy: boolean;
  disabledReason: string | null;
  results: SearchResult[];
  onSearch: (query: string, limit: number) => Promise<void>;
}

export function SearchPanel({
  activeCollection,
  busy,
  disabledReason,
  results,
  onSearch,
}: SearchPanelProps) {
  const [query, setQuery] = useState("");
  const [limit, setLimit] = useState(5);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!query.trim()) {
      return;
    }
    await onSearch(query.trim(), limit);
  }

  return (
    <section className="panel search-panel" aria-labelledby="search-title">
      <div className="panel__heading">
        <div>
          <span className="eyebrow">HYBRID RETRIEVAL</span>
          <h2 id="search-title">检索知识库</h2>
        </div>
        <span className="panel__step">02</span>
      </div>

      <form className="search-form" onSubmit={submit}>
        <div className="search-box">
          <Search size={19} aria-hidden="true" />
          <input
            value={query}
            disabled={!activeCollection || busy}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="例如：WebGPU 不支持时会发生什么？"
            aria-label="检索问题"
          />
          <select
            value={limit}
            onChange={(event) => setLimit(Number(event.target.value))}
            aria-label="返回结果数量"
          >
            {[3, 5, 10].map((value) => (
              <option value={value} key={value}>
                Top {value}
              </option>
            ))}
          </select>
          <button
            className="button button--primary search-button"
            type="submit"
            disabled={!activeCollection || busy || !query.trim()}
          >
            搜索
          </button>
        </div>
      </form>

      {disabledReason ? (
        <div className="empty-state">
          <strong>{disabledReason}</strong>
          <p>完成导入后即可检索。查询向量仍会在当前浏览器中生成。</p>
        </div>
      ) : results.length === 0 ? (
        <div className="empty-state">
          <strong>等待检索</strong>
          <p>结果由 seekdb 的全文与向量 RRF 融合产生，返回原文和元数据。</p>
        </div>
      ) : (
        <div className="result-list" aria-live="polite">
          {results.map((result, index) => (
            <article className="result-row" key={result.id}>
              <span className="result-row__rank">{String(index + 1).padStart(2, "0")}</span>
              <div className="result-row__body">
                <p>{result.text}</p>
                <div className="result-row__meta">
                  <span>{String(result.metadata?.source ?? "未知来源")}</span>
                  <span>chunk {String(result.metadata?.chunk ?? "-")}</span>
                  <span>
                    {result.score === null ? "RRF" : result.score.toFixed(4)}
                  </span>
                </div>
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

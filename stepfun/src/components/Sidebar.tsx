import { useState } from "react";
import { Database, Plus, Trash2 } from "lucide-react";

import type { KnowledgeBase } from "../types";

interface SidebarProps {
  bases: KnowledgeBase[];
  activeId: string | null;
  busy: boolean;
  onSelect: (id: string) => void;
  onCreate: (name: string) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
}

export function Sidebar({
  bases,
  activeId,
  busy,
  onSelect,
  onCreate,
  onDelete,
}: SidebarProps) {
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!name.trim()) {
      return;
    }
    await onCreate(name.trim());
    setName("");
    setCreating(false);
  }

  return (
    <aside className="sidebar">
      <div className="brand">
        <span className="brand__mark" aria-hidden="true">
          EC
        </span>
        <div>
          <strong>Edge Course Lens</strong>
          <small>Local-first retrieval lab</small>
        </div>
      </div>

      <div className="sidebar__section">
        <div className="sidebar__heading">
          <span>知识库</span>
          <button
            className="icon-button icon-button--dark"
            type="button"
            title="新建知识库"
            aria-label="新建知识库"
            onClick={() => setCreating((value) => !value)}
          >
            <Plus size={16} />
          </button>
        </div>

        {creating ? (
          <form className="create-form" onSubmit={submit}>
            <label htmlFor="new-collection">名称</label>
            <input
              id="new-collection"
              value={name}
              maxLength={80}
              onChange={(event) => setName(event.target.value)}
              placeholder="例如：数据库课程"
              autoFocus
            />
            <div className="create-form__actions">
              <button className="button button--light button--small" type="submit" disabled={busy}>
                创建
              </button>
              <button
                className="text-button"
                type="button"
                onClick={() => setCreating(false)}
              >
                取消
              </button>
            </div>
          </form>
        ) : null}

        <div className="collection-list">
          {bases.length === 0 ? (
            <div className="sidebar-empty">
              <Database size={20} />
              <p>还没有知识库。新建一个后导入文本。</p>
            </div>
          ) : (
            bases.map((base) => (
              <div
                className={`collection-row ${base.id === activeId ? "is-active" : ""}`}
                key={base.id}
              >
                <button
                  className="collection-row__main"
                  type="button"
                  onClick={() => onSelect(base.id)}
                >
                  <span>{base.name}</span>
                  <small>{base.count} 个文本块</small>
                </button>
                <button
                  className="icon-button icon-button--dark collection-row__delete"
                  type="button"
                  title={`删除 ${base.name}`}
                  aria-label={`删除 ${base.name}`}
                  onClick={() => void onDelete(base.id)}
                >
                  <Trash2 size={14} />
                </button>
              </div>
            ))
          )}
        </div>
      </div>

      <div className="sidebar__foot">
        <span>Embedding</span>
        <strong>bge-small-zh-v1.5</strong>
        <small>ONNX · 512 dimensions</small>
      </div>
    </aside>
  );
}

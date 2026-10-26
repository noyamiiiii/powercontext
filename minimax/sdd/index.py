"""Real seekdb collection ingestion and retrieval; no canned context responses."""
import ast
import hashlib
import math
import re
from pathlib import Path
import pyseekdb
from pyseekdb import HNSWConfiguration
from .common import digest, now, read_json, safe_source, write_json

DIMENSION = 128

def embed(text):
    """Local deterministic token hashing, not a neural semantic embedding."""
    terms = re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]", text.lower())
    vec = [0.0] * DIMENSION
    for term in terms:
        raw = hashlib.sha256(term.encode()).digest()
        vec[int.from_bytes(raw[:4], "big") % DIMENSION] += 1.0 if raw[4] & 1 else -1.0
    norm = math.sqrt(sum(v*v for v in vec))
    if not norm:
        vec[0] = 1.0
        return vec
    return [v/norm for v in vec]

def chunks(path, text):
    lines = text.splitlines(keepends=True)
    if path.endswith(".py"):
        nodes = [n for n in ast.parse(text).body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
        ranges = [(min([n.lineno] + [d.lineno for d in n.decorator_list]), n.end_lineno, n.name) for n in nodes]
    elif path.endswith(".md"):
        starts = [i for i, line in enumerate(lines, 1) if line.startswith("## ")]
        ranges = [(start, (starts[i+1]-1 if i+1 < len(starts) else len(lines)), lines[start-1].strip("# \n")) for i, start in enumerate(starts)]
    else:
        ranges = []
    # Include whole files too, preserving imports, fixtures and module-level constants.
    yield 1, len(lines), "<file>", text
    for start, end, symbol in ranges:
        yield start, end, symbol, "".join(lines[start-1:end])

class EngineeringIndex:
    def __init__(self, root, runtime):
        self.root = Path(root).resolve()
        self.runtime = Path(runtime).resolve()
        self.runtime.mkdir(parents=True, exist_ok=True)
        self.client = pyseekdb.Client(path=str(self.runtime / "seekdb"), database="test")
        self.collection = self.client.get_or_create_collection(
            "engineering_sources", configuration=HNSWConfiguration(dimension=DIMENSION), embedding_function=None)

    def ingest(self):
        manifest = read_json(self.root / "project.json")
        records = []
        for entry in manifest["files"]:
            text = safe_source(self.root, entry["path"]).read_text(encoding="utf-8")
            for start, end, symbol, content in chunks(entry["path"], text):
                identity = f'{manifest["project"]}:{entry["path"]}:{symbol}'
                records.append((digest(identity), content, {
                    **entry, "project": manifest["project"], "start": start, "end": end,
                    "symbol": symbol, "file_hash": digest(text), "content_hash": digest(content)}))
        # Upsert current rows first; remove stale rows after successful writes.
        self.collection.upsert(ids=[r[0] for r in records], documents=[r[1] for r in records],
            metadatas=[r[2] for r in records], embeddings=[embed(r[1]+" "+r[2]["module"]) for r in records])
        current = set(r[0] for r in records)
        old = self.collection.get(where={"project": manifest["project"]}, include=["metadatas"])["ids"]
        stale = sorted(set(old)-current)
        if stale:
            self.collection.delete(ids=stale)
        self.collection.refresh_index()
        result = {"time": now(), "backend": "seekdb", "operation": "upsert", "records": len(records), "deleted": stale,
            "file_hashes": {r[2]["path"]: r[2]["file_hash"] for r in records}}
        write_json(self.runtime / "ingest.json", result)
        return result

    def context(self, task):
        project = read_json(self.root / "project.json")["project"]
        count = self.collection.count()
        if not count:
            raise ValueError("Index is empty; run ingest first")
        self.collection.refresh_index()
        # Search real persisted vectors, then expand the selected modules for coverage.
        query_args = {"query_embeddings": [embed(task["query"])], "n_results": min(6, count),
                      "where": {"project": project}, "include": ["documents", "metadatas", "distances"]}
        hits = self.collection.query(**query_args)
        modules = sorted({meta["module"] for meta in hits["metadatas"][0]})
        if not modules:
            raise ValueError("No engineering sources match this task")
        where = {"$and": [{"project": project}, {"module": {"$in": modules}}, {"symbol": "<file>"}]}
        expanded = self.collection.get(where=where, include=["documents", "metadatas"])
        sources = []
        for row_id, document, metadata in zip(expanded["ids"], expanded["documents"], expanded["metadatas"]):
            path = safe_source(self.root, metadata["path"])
            if digest(path.read_text(encoding="utf-8")) != metadata["file_hash"]:
                raise ValueError(f'Stale index for {metadata["path"]}; run ingest again')
            sources.append({"id": row_id, **metadata, "content": document})
        sources.sort(key=lambda x: (x["kind"], x["path"]))
        spec_text = "\n".join(s["content"] for s in sources if s["kind"] == "spec")
        missing = sorted(set(task.get("required_sources", [])) - {s["path"] for s in sources})
        missing_ids = [s for s in task.get("required_spec_ids", []) if s not in spec_text]
        if missing or missing_ids:
            raise ValueError(f"Missing required sources/specifications: {missing + missing_ids}")
        result = {"task_id": task["task_id"], "query": task["query"], "sources": sources,
            "database": {"backend": "seekdb", "collection": "engineering_sources", "modules": modules,
                         "query_ids": hits["ids"][0], "distances": hits["distances"][0], "expanded_ids": expanded["ids"]}}
        write_json(self.runtime / "database-query.json", {"time": now(), "query": task["query"],
            "query_vector_sha256": digest(str(query_args["query_embeddings"])), "where": query_args["where"],
            "expansion_filter": where, "result": result["database"]})
        return result

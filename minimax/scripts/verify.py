"""Generate reproducible real test, seekdb, and PowerContext evidence."""
import argparse
import difflib
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sdd.common import ROOT, digest, now, read_json, write_json

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, default=ROOT / "evidence")
    args = parser.parse_args()
    evidence = args.evidence.resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    results = []
    source_files = [p for folder in ("sdd", "scripts", "tests", "sample_project", "snapshots") for p in (ROOT / folder).rglob("*.py") if "__pycache__" not in p.parts]
    source_hashes = {p.relative_to(ROOT).as_posix(): digest(p.read_text()) for p in sorted(source_files)}
    source_version = digest(json.dumps(source_hashes, sort_keys=True))
    write_json(evidence / "source-version.json", {"sha256": source_version, "files": source_hashes})
    with tempfile.TemporaryDirectory(prefix="minimax-sdd-verify-") as temporary:
        stage = Path(temporary)
        shutil.copytree(ROOT / "sample_project", stage / "sample_project", ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
        shutil.copy(ROOT / "pyproject.toml", stage)
        shutil.copy(ROOT / "project.json", stage)
        shutil.copy(ROOT / "task.json", stage)
        target = stage / "sample_project/orders.py"
        test_file = stage / "sample_project/tests/test_orders.py"
        suite_hash = digest(test_file.read_text())

        def run(name, arguments, cwd=stage, expected=0, version=None):
            command = [sys.executable, *arguments]
            result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=180,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": str(ROOT)})
            stdout = result.stdout.replace(str(stage), "<workspace>").replace(str(ROOT), "<submission>")
            stderr = result.stderr.replace(str(stage), "<workspace>").replace(str(ROOT), "<submission>")
            record = {"name": name, "time": now(), "command": ["python", *arguments], "exit_code": result.returncode,
                "expected_exit_code": expected, "code_sha256": version or source_version, "test_suite_sha256": suite_hash}
            (evidence / f"{name}.log").write_text(json.dumps(record, indent=2)+"\n\n"+stdout+stderr, encoding="utf-8")
            results.append(record)
            if result.returncode != expected:
                raise RuntimeError(f"{name} failed: {stdout[-3000:]}{stderr[-2000:]}")
            return result

        before = (ROOT / "snapshots/before.py").read_text()
        after = (ROOT / "sample_project/orders.py").read_text()
        target.write_text(before)
        baseline = run("before-target", ["-m", "pytest", "sample_project/tests/test_orders.py", "-m", "target", "-q", "--tb=short"], expected=1, version=digest(before))
        if "ERROR" in baseline.stdout or not any(s in baseline.stdout for s in ("AssertionError", "DID NOT RAISE")):
            raise RuntimeError("Baseline failure was not established as a functional assertion failure")
        run("before-regression", ["-m", "pytest", "sample_project/tests/test_orders.py", "-m", "regression", "-q"], version=digest(before))
        target.write_text(after)
        run("after-target", ["-m", "pytest", "sample_project/tests/test_orders.py", "-m", "target", "-q"], version=digest(after))
        run("after-regression", ["-m", "pytest", "sample_project/tests/test_orders.py", "-m", "regression", "-q"], version=digest(after))
        assert digest(test_file.read_text()) == suite_hash
        (evidence / "code.diff").write_text("".join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
            fromfile="before/sample_project/orders.py", tofile="after/sample_project/orders.py")), encoding="utf-8")
        (ROOT / "snapshots/after.py").write_text(after)
        run("module-tests", ["-m", "pytest", "tests", "-q"], cwd=ROOT,
            version=digest("".join(p.read_text() for p in sorted((ROOT / "sdd").glob("*.py")))))
        runtime = stage / "runtime"
        # Each CLI call is a new OS process; the first exits before the next starts.
        empty = stage / "empty.json"
        run("state-empty", ["-m", "sdd.cli", "resume", "--runtime", str(runtime), "--out", str(empty)])
        assert read_json(empty)["state"] is None
        run("database-ingest", ["-m", "sdd.cli", "ingest", "--root", str(stage), "--runtime", str(runtime)])
        context_file = stage / "context.json"
        run("context-before", ["-m", "sdd.cli", "context", "--root", str(stage), "--runtime", str(runtime), "--out", str(context_file)])
        write_json(evidence / "context.json", read_json(context_file))
        checkpoint = stage / "checkpoint.json"
        write_json(checkpoint, {"done": ["ingested specifications, code and tests", "implemented status filter", "target and regression tests passed"],
            "todo": ["review MiniMax provenance and submit"], "validations": results[:4]})
        run("powercontext-write", ["-m", "sdd.cli", "save", "--runtime", str(runtime), "--state", str(checkpoint)])
        resumed = stage / "context-resumed.json"
        run("context-resumed", ["-m", "sdd.cli", "context", "--root", str(stage), "--runtime", str(runtime), "--out", str(resumed)])
        recovered = read_json(resumed)
        assert recovered["progress"]["state"]["done"] == read_json(checkpoint)["done"]
        assert recovered["progress"]["state"]["validations"][2]["exit_code"] == 0
        write_json(evidence / "context-resumed.json", recovered)
        shutil.copy(runtime / "database-query.json", evidence / "database-query.json")
        shutil.copy(runtime / "ingest.json", evidence / "database-ingest.json")
        spec = stage / "sample_project/spec.md"
        spec.write_text(spec.read_text()+"\n## ORD-005: New version probe\nThe next task must consider refunded status.\n")
        run("spec-reimport", ["-m", "sdd.cli", "ingest", "--root", str(stage), "--runtime", str(runtime)])
        updated = stage / "context-updated.json"
        run("spec-updated-context", ["-m", "sdd.cli", "context", "--root", str(stage), "--runtime", str(runtime), "--out", str(updated)])
        changed = read_json(updated)
        assert any("ORD-005" in s["content"] for s in changed["sources"] if s["kind"] == "spec")
        write_json(evidence / "context-spec-updated.json", changed)

    provenance = evidence / "minimax-provenance.json"
    model_used = False
    if provenance.is_file() and (evidence / "minimax-request.json").is_file() and (evidence / "minimax-response.json").is_file():
        origin = read_json(provenance)
        request = read_json(evidence / "minimax-request.json")
        response = read_json(evidence / "minimax-response.json")
        delivered = json.loads(response["delivered_content"])
        model_used = (origin.get("after_sha256") == digest(after) and origin.get("before_sha256") == digest(before)
            and delivered.get("path") == "sample_project/orders.py" and delivered.get("content") == after
            and origin.get("response_id") == response.get("id") and bool(response.get("id"))
            and "minimax" in str(response.get("model", "")).lower()
            and request["request"]["model"] == response.get("requested_model"))
    summary = {"time": now(), "results": results, "same_suite_sha256": suite_hash,
        "before_sha256": digest(before), "after_sha256": digest(after), "source_version_sha256": source_version,
        "acceptance": {"runnable": True, "minimax_participated": model_used, "context_correct": True,
            "database_used": True, "state_reused_after_process_restart": True, "code_change_effective": True},
        "complete": model_used}
    write_json(evidence / "summary.json", summary)
    write_json(evidence / "technology-use.json", {"time": now(), "python": sys.version,
        "versions": {package: importlib.metadata.version(package) for package in ("powercontext", "pyseekdb", "pylibseekdb", "pytest")},
        "minimax": {"record": "minimax-provenance.json", "verified_against_delivered_source": model_used},
        "seekdb": {"mode": "embedded", "operations": ["upsert", "refresh_index", "query", "get", "delete"]},
        "powercontext": {"mode": "builtin runtime with persistent SQLite", "operations": ["scopes.create", "sources.capture", "records.list_sources"],
                         "process_restart_verified": True}})
    print(json.dumps(summary, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()

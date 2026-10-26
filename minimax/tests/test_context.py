import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import pytest
from sdd.common import ROOT, read_json
from sdd.index import EngineeringIndex

@pytest.fixture(scope="module")
def project(tmp_path_factory):
    root = tmp_path_factory.mktemp("engineering-project")
    shutil.copytree(ROOT / "sample_project", root / "sample_project", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy(ROOT / "project.json", root)
    shutil.copy(ROOT / "task.json", root)
    index = EngineeringIndex(root, tmp_path_factory.mktemp("seekdb"))
    index.ingest()
    return root, index, read_json(root / "task.json")

@pytest.mark.integration
def test_real_database_context_has_sources_and_spec_ids(project):
    root, index, task = project
    context = index.context(task)
    assert set(task["required_sources"]) == {s["path"] for s in context["sources"]}
    assert context["database"]["query_ids"]
    specs = "".join(s["content"] for s in context["sources"] if s["kind"] == "spec")
    assert all(spec in specs for spec in task["required_spec_ids"])
    assert all((root / source["path"]).is_file() for source in context["sources"])

@pytest.mark.integration
def test_spec_update_requires_ingestion_and_returns_current_content(project):
    root, index, task = project
    spec = root / "sample_project/spec.md"
    original = spec.read_text()
    try:
        spec.write_text(original + "\n## ORD-005: Changed requirement\nSupport refunded orders in the NEXT task only.\n")
        with pytest.raises(ValueError, match="Stale index"):
            index.context(task)
        index.ingest()
        updated = index.context(task)
        assert "ORD-005" in "".join(s["content"] for s in updated["sources"] if s["kind"] == "spec")
    finally:
        spec.write_text(original)
        index.ingest()

@pytest.mark.integration
def test_deleted_manifest_source_does_not_survive_ingestion(project):
    root, index, task = project
    manifest = root / "project.json"
    original = manifest.read_text()
    data = json.loads(original)
    data["files"] = [f for f in data["files"] if f["kind"] != "data"]
    try:
        manifest.write_text(json.dumps(data))
        index.ingest()
        with pytest.raises(ValueError, match="Missing required sources"):
            index.context(task)
    finally:
        manifest.write_text(original)
        index.ingest()

@pytest.mark.integration
def test_state_is_reused_by_an_independent_process(tmp_path):
    runtime = tmp_path / "state-runtime"
    checkpoint = tmp_path / "checkpoint.json"
    checkpoint.write_text(json.dumps({"done": ["context selected"], "todo": ["execute target tests"],
        "validations": [{"command": "pytest", "exit_code": 0}]}))
    def run(command, *extra):
        result = subprocess.run([sys.executable, "-m", "sdd.cli", command, "--runtime", str(runtime), *extra],
            cwd=ROOT, text=True, capture_output=True, timeout=120, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        assert result.returncode == 0, result.stdout + result.stderr
        return json.loads(result.stdout)
    assert run("resume")["state"] is None
    saved = run("save", "--state", str(checkpoint))
    restored = run("resume")
    assert saved["scope_id"] == restored["scope_id"]
    assert restored["state"]["done"] == ["context selected"]
    assert restored["state"]["todo"] == ["execute target tests"]
    assert restored["state"]["validations"][0]["exit_code"] == 0

def test_source_paths_cannot_escape_project(tmp_path):
    from sdd.common import safe_source
    external = tmp_path / "outside.txt"
    external.write_text("outside")
    root = tmp_path / "project"
    root.mkdir()
    with pytest.raises(ValueError):
        safe_source(root, "../outside.txt")

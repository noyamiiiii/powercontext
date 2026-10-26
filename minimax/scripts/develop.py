"""Make a real MiniMax modification in a disposable baseline workspace."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sdd.common import ROOT, digest, read_json, write_json

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, help="Optional untracked dotenv file containing MiniMax settings")
    args = parser.parse_args()
    if args.env_file:
        from dotenv import load_dotenv
        load_dotenv(args.env_file.resolve(), override=True)
    if not os.environ.get("MINIMAX_API_KEY"):
        parser.error("Set MINIMAX_API_KEY or pass --env-file; no model invocation can be simulated")
    from sdd.agent import generate
    from sdd.index import EngineeringIndex
    from sdd.state import TaskState
    with tempfile.TemporaryDirectory(prefix="minimax-sdd-develop-") as temporary:
        stage = Path(temporary)
        shutil.copytree(ROOT / "sample_project", stage / "sample_project", ignore=shutil.ignore_patterns("__pycache__"))
        for name in ("project.json", "task.json", "pyproject.toml"):
            shutil.copy(ROOT / name, stage)
        task = read_json(stage / "task.json")
        before = (ROOT / "snapshots/before.py").read_text()
        target = stage / task["target"]
        target.write_text(before)
        runtime = stage / ".runtime"
        index = EngineeringIndex(stage, runtime)
        index.ingest()
        context = index.context(task)
        # Development continues from a real PowerContext checkpoint.
        state = TaskState(runtime)
        asyncio.run(state.access(task["task_id"], {"done": ["baseline engineering sources imported"],
            "todo": ["implement ORD-002 and ORD-003", "run target and regression tests"], "validations": []}))
        context["progress"] = asyncio.run(state.access(task["task_id"]))
        record = generate(stage, task, context, ROOT / "evidence")
        tests = subprocess.run([sys.executable, "-m", "pytest", "sample_project/tests", "-q"],
            cwd=stage, capture_output=True, text=True, timeout=120,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": str(stage)})
        write_json(ROOT / "evidence/minimax-generated-tests.json", {"command": "python -m pytest sample_project/tests -q",
            "exit_code": tests.returncode, "code_sha256": digest(target.read_text()), "stdout": tests.stdout, "stderr": tests.stderr})
        if tests.returncode:
            raise RuntimeError("MiniMax generated code did not pass the unchanged suite; delivered source was preserved")
        shutil.copy(target, ROOT / task["target"])
        shutil.copy(target, ROOT / "snapshots/after.py")
        print(json.dumps(record, indent=2))

if __name__ == "__main__":
    main()

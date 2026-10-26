"""CLI: python -m sdd.cli {ingest,context,save,resume,generate}."""
import argparse
import asyncio
import json
from pathlib import Path
from .common import ROOT, read_json, write_json

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["ingest", "context", "save", "resume", "generate"])
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--runtime", type=Path, default=ROOT / ".runtime")
    parser.add_argument("--task", type=Path)
    parser.add_argument("--state", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    root, runtime = args.root.resolve(), args.runtime.resolve()
    task = read_json(args.task or root / "task.json")
    from .state import TaskState
    if args.command == "ingest":
        from .index import EngineeringIndex
        result = EngineeringIndex(root, runtime).ingest()
    elif args.command in {"save", "resume"}:
        if args.command == "save" and args.state is None:
            parser.error("save requires --state JSON containing done, todo, and validations")
        result = asyncio.run(TaskState(runtime).access(task["task_id"], read_json(args.state) if args.command == "save" else None))
    else:
        from .index import EngineeringIndex
        context = EngineeringIndex(root, runtime).context(task)
        context["progress"] = asyncio.run(TaskState(runtime).access(task["task_id"]))
        if args.command == "generate":
            from .agent import generate
            result = generate(root, task, context, args.out or root / "evidence")
        else:
            result = context
    if args.out and args.command != "generate":
        write_json(args.out, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()

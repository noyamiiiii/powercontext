"""A bounded MiniMax editing step, with an auditable request and code response."""
import ast
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from .common import digest, now, safe_source, write_json

def generate(root, task, context, evidence):
    key = os.environ.get("MINIMAX_API_KEY")
    if not key:
        raise ValueError("MINIMAX_API_KEY is required for a real MiniMax development record")
    base = os.environ.get("MINIMAX_BASE_URL", "https://api.minimax.io/v1").rstrip("/")
    if not base.startswith("https://"):
        raise ValueError("MiniMax requests require an HTTPS endpoint")
    model = os.environ.get("MINIMAX_MODEL", "MiniMax-M3.1-Flash")
    style = os.environ.get("MINIMAX_API_STYLE", "openai")
    suffix = {"openai": "/chat/completions", "native": "/text/chatcompletion_v2", "anthropic": "/messages"}.get(style)
    if suffix is None:
        raise ValueError("MINIMAX_API_STYLE must be openai, native, or anthropic")
    endpoint = base + suffix
    if "minimax" not in model.lower():
        raise ValueError("This task requires an explicitly named MiniMax model")
    before = safe_source(root, task["target"]).read_text(encoding="utf-8")
    prompt = ("Complete this local development task using the supplied current project context. "
        "Preserve existing behavior and tests. Return only a JSON object with keys path and content, "
        "where content is the complete updated Python source for the single permitted target file. "
        "Do not include reasoning or modify any test.\n" + json.dumps({"task": task, "context": context}, ensure_ascii=False))
    body = {"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.1, "max_tokens": 6000}
    evidence = Path(evidence)
    evidence.mkdir(parents=True, exist_ok=True)
    write_json(evidence / "minimax-request.json", {"time": now(), "endpoint": endpoint, "api_style": style, "request": body})
    headers = {"Authorization": "Bearer " + key, "Content-Type": "application/json"}
    if style == "anthropic":
        headers.update({"x-api-key": key, "anthropic-version": "2023-06-01"})
    request = urllib.request.Request(endpoint, data=json.dumps(body).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            data = json.load(response)
            request_id = response.headers.get("x-request-id")
    except urllib.error.HTTPError as error:
        detail = error.read(4096).decode("utf-8", errors="replace").replace(key, "[REDACTED]")
        write_json(evidence / "minimax-error.json", {"time": now(), "status": error.code, "model": model, "detail": detail})
        raise RuntimeError(f"MiniMax API returned HTTP {error.code}: {detail[:600]}") from None
    if data.get("base_resp", {}).get("status_code", 0):
        status = data["base_resp"]["status_code"]
        detail = str(data["base_resp"].get("status_msg", "")).replace(key, "[REDACTED]")
        write_json(evidence / "minimax-error.json", {"time": now(), "status_code": status, "model": model, "detail": detail})
        raise RuntimeError(f"MiniMax API rejected the request with status_code={status}: {detail}")
    if style == "anthropic":
        text = "\n".join(part["text"] for part in data["content"] if part.get("type") == "text")
        finish_reason = data.get("stop_reason")
    else:
        text = data["choices"][0]["message"]["content"]
        finish_reason = data["choices"][0].get("finish_reason")
    # Private reasoning is unnecessary for this submission; retain only the delivered code.
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text).strip()
    write_json(evidence / "minimax-response.json", {"time": now(), "id": data.get("id"),
        "request_id": request_id, "model": data.get("model"), "requested_model": model,
        "usage": data.get("usage"), "finish_reason": finish_reason, "delivered_content": text})
    result = json.loads(text)
    if result["path"] != task["target"]:
        raise ValueError("MiniMax attempted to modify a file outside the permitted target")
    ast.parse(result["content"])
    if result["content"] == before:
        raise ValueError("MiniMax returned unchanged code; this is not a completed modification")
    target = safe_source(root, result["path"])
    pending = target.with_suffix(".py.pending")
    pending.write_text(result["content"], encoding="utf-8")
    pending.replace(target)
    provenance = {"time": now(), "model": data.get("model"), "requested_model": model,
        "response_id": data.get("id"), "request_id": request_id, "target": result["path"],
        "before_sha256": digest(before), "after_sha256": digest(result["content"]),
        "context_sha256": digest(json.dumps(context, ensure_ascii=False, sort_keys=True))}
    write_json(evidence / "minimax-provenance.json", provenance)
    (evidence / "minimax-error.json").unlink(missing_ok=True)
    return provenance

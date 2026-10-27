from __future__ import annotations

from pathlib import Path

import yaml

DSL_PATH = Path(__file__).resolve().parents[2] / "dsl" / "outlandish-travel-agency.yml"


def test_dsl_contains_required_chatflow_nodes_and_links() -> None:
    data = yaml.safe_load(DSL_PATH.read_text(encoding="utf-8"))
    nodes = data["workflow"]["graph"]["nodes"]
    edges = data["workflow"]["graph"]["edges"]
    node_types = [node["data"]["type"] for node in nodes]
    node_ids = [node["id"] for node in nodes]

    assert data["app"]["mode"] == "advanced-chat"
    assert data["version"] == "0.6.0"
    assert len(node_ids) == len(set(node_ids))
    assert node_types == ["start", "code", "http-request", "llm", "code", "http-request", "answer"]
    assert any(node["data"]["type"] == "llm" for node in nodes)
    assert sum(node["data"]["type"] == "http-request" for node in nodes) == 2
    assert all(edge["source"] in node_ids and edge["target"] in node_ids for edge in edges)
    assert len(edges) == len(nodes) - 1

    urls = [node["data"].get("url") for node in nodes if node["data"]["type"] == "http-request"]
    assert urls == [
        "http://host.docker.internal:8766/v1/recall",
        "http://host.docker.internal:8766/v1/remember",
    ]

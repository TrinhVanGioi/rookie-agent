"""Gate 9 (task 9.4): the twin of a process. A flow's API calls are answered from the skeletons kept with it (`shape.py`), not by the
system; a flow without API calls (a Java one) is shown as its screen steps with a simulated time. Nothing here touches IE or the
network. The run itself is `replay.run_api(..., twin=True)`: a node that writes or moves money, and a checker's stage, wait for the
person's Duyệt."""

from __future__ import annotations

import copy
from typing import Any, Callable

from rookie_agent.ie import shape

SCREEN_MS = {"fill": 2500, "select": 1800, "click": 1200, "submit": 1500}
DEFAULT_MS = 120
NO_TWIN = "Luồng này học trước khi có bản sao, hãy Ghi và Học lại."


def make_twin_send(inputs: dict[str, str], seed: str = "") -> Callable[[dict[str, Any], str, str, str], dict[str, Any]]:
    """`send(node, url, headers, body)` for `run_api`: status 200, the recorded time of the call when it is known, a fake answer
    that is the same for the same inputs and seed."""
    def twin_send(node: dict[str, Any], url: str, headers: str, body: str) -> dict[str, Any]:
        skeleton = node.get("shape")
        if not skeleton:
            return {"ok": False, "status": 0, "ms": 0, "error": "chưa có bản sao của trả lời này"}
        return {"ok": True, "status": 200, "ms": int(node.get("ms") or DEFAULT_MS), "text": shape.fake(skeleton, inputs, seed + "|" + node["id"])}
    return twin_send


def has_twin(api: list[dict[str, Any]]) -> bool:
    return bool(api) and all(n.get("shape") for n in api)


def screen_nodes(workflow: dict[str, Any], describe: Callable[[dict[str, Any]], str]) -> list[dict[str, Any]]:
    """The steps of a flow that has no API calls, as nodes the twin passes with a simulated time."""
    return [{"id": step["id"], "step_id": step["id"], "kind": "screen", "label": describe(step), "frame": "top", "method": "SCREEN",
             "url": "", "headers": "", "body": "", "links": {}, "risk": step.get("risk", "read"), "complete": True, "unresolved": [],
             "answer": "", "ms": SCREEN_MS.get(str(step.get("action")), 1000), "shape": None} for step in workflow.get("steps", [])]


def prefixed(nodes: list[dict[str, Any]], prefix: str, stage_label: str) -> list[dict[str, Any]]:
    """The nodes of one stage with ids that do not clash with another stage's (links follow)."""
    out = []
    for node in nodes:
        copy_ = copy.deepcopy(node)
        copy_["id"] = prefix + node["id"]
        copy_["label"] = f"[{stage_label}] {node['label']}" if stage_label else node["label"]
        copy_["links"] = {k: {**v, "from": prefix + str(v["from"])} for k, v in node.get("links", {}).items()}
        out.append(copy_)
    return out

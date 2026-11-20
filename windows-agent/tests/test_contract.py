"""Task 12.4 (SADPT): a call whose answer comes back in another form than when it was learned (the service changed) is not trusted:
nothing more is sent, the call is marked to be checked, and the teller is told to run on the screen."""

from __future__ import annotations

import json
import threading

from rookie_agent.ie import replay
from test_replay import ANSWERS, Shown, flow, nodes


def run(answers, **options):
    sent = []

    def send(node, url, headers, body):
        sent.append(url)
        return {"ok": True, "status": 200, "ms": 3, "text": answers.get(url, "")}

    return replay.run_api(flow(), nodes()[:3], {"cif": "9988776655"}, send, Shown(), threading.Event(), **options), sent


def test_the_nodes_keep_the_form_of_each_answer_from_learning_and_no_value():
    kinds = [(n["url"], (n.get("shape") or {}).get("kind")) for n in nodes()[:3]]
    assert kinds == [("/tp/init", "json"), ("/tp/find", "gwt"), ("/tp/detail", "empty")]      # (the last one answered nothing while recording)
    assert "TRAN" not in json.dumps([n["shape"] for n in nodes()[:3]])


def test_an_answer_in_another_form_stops_before_the_next_call_and_says_so_in_plain_words():
    changed = {**ANSWERS, "/tp/find": "<FindRs><Status>0</Status><Customer><Name>TRAN THI B</Name></Customer></FindRs>"}
    result, sent = run(changed)
    assert result["status"] == "needs_help" and sent == ["/tp/init", "/tp/find"]
    assert "dạng khác" in result["message"] and "trên màn hình" in result["message"]
    (row,) = result["decisions"]
    assert row["saw"] == "contract_changed" and row["change"] == "technical" and row["action"] == "ask" and row["where"]["kind"] == "gwt>xml"
    assert result["contract_changed"] == [nodes()[1]["id"]] and "TRAN" not in json.dumps(result["decisions"])


def test_the_same_form_goes_on_and_the_twin_never_checks_its_own_fakes():
    assert run(ANSWERS)[0]["status"] == "finished"
    twin, _ = run({**ANSWERS, "/tp/find": "<x/>"}, twin=True)
    assert "contract_changed" not in twin


def test_a_call_marked_to_be_checked_sends_nothing_of_the_flow_until_it_is_learned_again():
    marked = nodes()[:3]
    marked[1]["needs_check"] = True
    sent = []
    result = replay.run_api(flow(), marked, {"cif": "1"}, lambda n, u, h, b: sent.append(u) or {"ok": True, "status": 200, "ms": 1, "text": ""},
                            Shown(), threading.Event())
    assert result["status"] == "needs_help" and sent == [] and "chờ xác minh" in result["message"]


def test_the_page_marks_the_call_on_the_flow_after_such_a_run(tmp_path, monkeypatch):
    from test_files import export_core, run_to_end

    core = export_core(tmp_path, monkeypatch, {"ok": True, "status": 200, "ms": 5, "text": "<Rs><A>1</A></Rs>"})
    flows = core.store.get("flows")
    flows[0]["workflow"] = {**flow(), "engine": "ie", "status": "approved"}
    flows[0]["api"] = nodes()[:3]                       # the first call was learned answering JSON; the server now answers XML
    core.store.put("flows", flows)
    run = run_to_end(core)
    assert run["result"]["status"] == "needs_help", run["result"]
    assert any(n.get("needs_check") for n in core.store.get("flows")[0]["api"])
    audit = (core.store.home / "audit.jsonl").read_text(encoding="utf-8")
    assert '"contract_changed"' in audit

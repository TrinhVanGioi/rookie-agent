"""The call to Genie Codie and its log. A fake `codie` (a Python script) stands in for the real one: no network, no model."""

import sys
from pathlib import Path

from rookie_agent import codie

FAKE = r'''
import sys
mode = sys.argv[sys.argv.index("--mode") + 1]
prompt = sys.argv[sys.argv.index("-p") + 1]
print(prompt)                      # Codie prints the prompt back first, with the sample markers in it
print("[task] active 1234")
if mode == "ok":
    print("thinking...\n<<<MV_RESULT\n{\"pong\": true}\nMV_RESULT>>>")
elif mode == "nomarker":
    print("done, no block")
elif mode == "two":
    print("<<<MV_RESULT\n{}\nMV_RESULT>>>\n<<<MV_RESULT\n{}\nMV_RESULT>>>")
elif mode == "badjson":
    print("<<<MV_RESULT\n{not json\nMV_RESULT>>>")
elif mode == "provider":
    print("Error: 500 UPSTREAM_ERROR from provider"); sys.exit(1)
elif mode == "exit3":
    print("boom"); sys.exit(3)
'''


def fake(tmp_path: Path) -> list[str]:
    script = tmp_path / "fake_codie.py"
    script.write_text(FAKE, encoding="utf-8")
    return [sys.executable, str(script)]


def run(tmp_path, mode, **kw):
    return codie.call(mode, codie.TEST_PROMPT, timeout_s=60, argv0=fake(tmp_path), **kw)


def test_a_marked_json_answer_is_the_result_and_the_prompts_own_sample_is_not(tmp_path):
    result = run(tmp_path, "ok")
    assert result.ok and result.result == {"pong": True}


def test_every_way_an_answer_can_be_wrong_is_told_in_plain_words(tmp_path):
    assert "không có khối kết quả" in run(tmp_path, "nomarker").reason
    assert "nhiều khối" in run(tmp_path, "two").reason
    assert "không phải JSON" in run(tmp_path, "badjson").reason
    assert "mô hình phía sau" in run(tmp_path, "provider").reason
    assert "mã 3" in run(tmp_path, "exit3").reason
    assert not any(run(tmp_path, m).ok for m in ("nomarker", "two", "badjson", "provider", "exit3"))


def test_a_missing_command_says_which_one_and_what_to_do():
    result = codie.call("ok", "x", command="no-such-codie-command-xyz")
    assert not result.ok and "no-such-codie-command-xyz" in result.reason and "Cài" in result.reason


def test_a_command_that_never_answers_times_out(tmp_path):
    script = tmp_path / "slow.py"
    script.write_text("import time; time.sleep(30)", encoding="utf-8")
    result = codie.call("ok", "x", timeout_s=1, argv0=[sys.executable, str(script)], args=[])
    assert not result.ok and "không trả lời" in result.reason


def test_a_long_prompt_is_passed_as_a_file_in_the_workspace(tmp_path):
    script = tmp_path / "echo.py"
    script.write_text('import sys\nprint("[task] active 1")\nprint("<<<MV_RESULT\\n" + \'{"arg": "%s"}\' % sys.argv[-1].split()[3] + "\\nMV_RESULT>>>")', encoding="utf-8")
    result = codie.call("ok", "x" * (codie.ARG_MAX + 10), argv0=[sys.executable, str(script)])
    assert result.ok and result.result["arg"].startswith("prompt-")


def test_the_log_keeps_facts_and_never_content(tmp_path):
    log = codie.CallLog(tmp_path)
    log.add("codie", "rookie-design", True, 12.34, prompt_chars=1500, note="đã trả kết quả")
    log.add("codie", "rookie-design", False, 0.5, note="Không tìm thấy lệnh")
    recent = log.recent()
    assert [e["ok"] for e in recent] == [False, True] and recent[1]["seconds"] == 12.3 and recent[1]["prompt_chars"] == 1500
    assert set(recent[0]) == {"time", "target", "mode", "ok", "seconds", "prompt_chars", "note"}


def test_the_log_is_kept_small(tmp_path):
    log = codie.CallLog(tmp_path, limit=5)
    for i in range(12):
        log.add("codie", "m", True, 0.1, note=str(i))
    assert [e["note"] for e in log.recent()] == ["11", "10", "9", "8", "7"]

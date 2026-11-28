import importlib.util
import json
import os
import subprocess
import sys
import time
from importlib.machinery import SourceFileLoader
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    loader = SourceFileLoader(name, str(path))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, loader))
    sys.modules[name] = module
    loader.exec_module(module)
    return module


orders = load("cr_orders_check", ROOT / "bin/orders-check")
facts = load("cr_facts", ROOT / "bin/facts")
reply = load("cr_reply_check", ROOT / ".claude/hooks/reply-check.py")

ORDERS = """| # | 지시 (사용자 말) | 날짜 | 상태 | 근거 / 남은 것 | 검사 | 안 본 것 |
|---|---|---|---|---|---|---|
| 1 | done and true | 11-28 | 끝남 | x | fast `true` | nothing |
| 2 | done but false | 11-28 | 끝남 | x | fast `echo a \\| grep -q b` | the rest |
| 3 | done, slow | 11-28 | 끝남 | x | `true` | |
| 4 | done, no check | 11-28 | 끝남 | x | | |
| 5 | still going | 11-28 | 진행 | x | fast `false` | |
"""


def test_an_orders_row_reads_its_check_its_speed_and_what_it_does_not_see():
    read = orders.orders_in(ORDERS)

    assert [(order.number, order.state, order.check, order.fast) for order in read] == [
        ("1", "끝남", "true", True), ("2", "끝남", "echo a | grep -q b", True), ("3", "끝남", "true", False),
        ("4", "끝남", "", False), ("5", "진행", "false", True),
    ]
    assert read[1].unseen == "the rest"


def test_a_done_row_whose_check_fails_or_is_missing_is_a_defect_and_open_rows_are_not_run():
    outcomes = {outcome.order.number: outcome for outcome in orders.check_all(orders.orders_in(ORDERS), fast_only=True)}

    assert {number: outcome.result for number, outcome in outcomes.items()} == {
        "1": "pass", "2": "fail", "3": "건너뜀 (fast 아님)", "4": "검사 없음"}
    assert [number for number, outcome in outcomes.items() if outcome.defect] == ["2", "4"]


def test_orders_check_exits_one_on_a_defect(tmp_path):
    written = tmp_path / "user-orders.md"
    written.write_text(ORDERS, encoding="utf-8")

    assert orders.main(["--fast", "--orders", str(written)]) == 1
    written.write_text(ORDERS.splitlines()[0] + "\n|---|\n| 1 | a | b | 끝남 | c | fast `true` | d |\n", encoding="utf-8")
    assert orders.main(["--fast", "--orders", str(written)]) == 0


def test_facts_lists_the_rows_not_done(tmp_path):
    written = tmp_path / "user-orders.md"
    written.write_text(ORDERS, encoding="utf-8")

    assert facts.open_orders(written) == ["#5 [진행] still going"]


def test_facts_tells_a_running_acceptance_from_a_stale_lock(tmp_path):
    lock = tmp_path / "acceptance.lock"
    assert facts.acceptance_state(lock) == "not running"
    lock.write_text(json.dumps({"pid": os.getpid(), "started": time.time(), "modules": "test_x"}))
    assert facts.acceptance_state(lock).startswith("running since") and "test_x" in facts.acceptance_state(lock)
    lock.write_text(json.dumps({"pid": 2 ** 22 + 12345, "started": time.time(), "modules": "all"}))
    assert facts.acceptance_state(lock).startswith("not running (stale lock")


def test_facts_never_reads_a_setting_it_does_not_name():
    assert facts.SETTING_LINE.match("/opt/cr/openstack.env:CR_STORE_PASSWORD=x")["key"] not in facts.SETTINGS


def test_a_question_without_its_context_is_sent_back_and_one_with_it_passes():
    assert "빠졌습니다" in reply.verdict("배포할까요?", [])
    assert reply.verdict("질문: 배포할지. 영향: VM이 20분 멈춤. 추천: 지금. 답이 없으면 10분 뒤 배포합니다. 할까요?", []) == ""
    assert reply.verdict("dev에 올렸습니다.", []) == ""
    assert reply.verdict("`ls?` 를 돌렸습니다.", []) == ""


def test_a_word_the_user_asked_about_needs_its_meaning_in_the_same_reply():
    assert "대본" in reply.verdict("대본를 다시 만들었습니다.", ["대본"])
    assert reply.verdict("대본(룰 테스트가 다시 보내는 요청)를 다시 만들었습니다.", ["대본"]) == ""


def hook(script, payload, **environment):
    return subprocess.run([str(ROOT / script)], input=payload, capture_output=True, text=True, timeout=20,
                          env={**os.environ, **environment})


def test_a_delegation_without_fresh_facts_is_denied(tmp_path):
    def decision(prompt):
        said = hook(".claude/hooks/before-delegate.sh", json.dumps({"tool_input": {"prompt": prompt}}),
                    CR_WORK_DIR=str(tmp_path)).stdout
        return json.loads(said)["hookSpecificOutput"].get("permissionDecision", "allow")

    assert decision("see facts.txt") == "deny"
    (tmp_path / "facts.txt").write_text("facts")
    assert decision("do the thing") == "deny"
    assert decision("from ~/.cache/fsl-work/facts.txt: dev is at x") == "allow"
    old = time.time() - 31 * 60
    os.utime(tmp_path / "facts.txt", (old, old))
    assert decision("see facts.txt") == "deny"


def test_a_push_to_a_branch_other_than_dev_passes_the_hook():
    done = subprocess.run([str(ROOT / ".githooks/pre-push"), "origin", "unused"], cwd=ROOT, text=True,
                          input="refs/heads/x 1111111111111111111111111111111111111111 refs/heads/work "
                                "0000000000000000000000000000000000000000\n",
                          capture_output=True, timeout=20)

    assert done.returncode == 0 and done.stdout == ""

import json
from datetime import datetime, timezone
from pathlib import Path

from testing.fakes import FakeRunner, FakeTarget, board_runner, corp_runner

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
TRUTH = json.loads((FIXTURES / "board-auth-users.json").read_text())
ROGUE_ADMIN_AT = datetime.fromtimestamp(1791106939, tz=timezone.utc)
CORP_STATE = {"wp_usermeta": "1\n", "wp_options": "users_can_register\t0\ndefault_role\tsubscriber\n",
              "wp_posts": "1\n"}


def corp_state_runner(binlog: str = "") -> FakeRunner:
    return corp_runner(CORP_STATE, binlog)


def board_target(truth: dict = TRUTH) -> FakeTarget:
    return FakeTarget({"board": board_runner(truth)})


def corp_target(binlog: str = "corp-rogue-admin.binlog") -> FakeTarget:
    return FakeTarget({"corp-db": corp_state_runner((FIXTURES / binlog).read_text())})

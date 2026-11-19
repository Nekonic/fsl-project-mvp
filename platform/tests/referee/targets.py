import json
from datetime import datetime, timezone
from pathlib import Path

from testing.fakes import FakeRunner, FakeTarget

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
TRUTH = json.loads((FIXTURES / "board-auth-users.json").read_text())
ROGUE_ADMIN_AT = datetime.fromtimestamp(1791106939, tz=timezone.utc)
CORP_STATE = {"wp_usermeta": "1\n", "wp_options": "users_can_register\t0\ndefault_role\tsubscriber\n",
              "wp_posts": "1\n"}


def board_runner(truth: dict) -> FakeRunner:
    return FakeRunner().answer("/internal/auth-users", json.dumps(truth))


def corp_runner(binlog: str = "") -> FakeRunner:
    runner = FakeRunner().answer("mysqlbinlog", binlog)
    for table, rows in CORP_STATE.items():
        runner.answer(table, rows)
    return runner


def board_target(truth: dict = TRUTH) -> FakeTarget:
    return FakeTarget({"board": board_runner(truth)})


def corp_target(binlog: str = "corp-rogue-admin.binlog") -> FakeTarget:
    return FakeTarget({"corp-db": corp_runner((FIXTURES / binlog).read_text())})

import json
from pathlib import Path

from cr import errors, strings
from domain.checks import DETAIL_CODES

STRINGS = Path(__file__).resolve().parents[3] / "strings"


def table(name):
    return json.loads((STRINGS / name).read_text(encoding="utf-8"))


def test_every_error_code_has_a_korean_line_in_the_console_table():
    shown = table("console.json")

    assert sorted(code for code in errors.CODES if f"error.{code}" not in shown) == []


def test_every_check_detail_code_has_a_korean_line_in_the_console_table():
    shown = table("console.json")

    assert sorted(code for code in DETAIL_CODES if f"check.{code}" not in shown) == []


def test_the_two_tables_share_no_key():
    assert set(table("console.json")) & set(table("server.json")) == set()


def test_the_server_reads_its_lines_from_its_own_table():
    assert strings.line("kibana.refused.home") == table("server.json")["kibana.refused.home"]

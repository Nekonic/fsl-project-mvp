from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone

MYSQL = ["env", "MYSQL_PWD=wordpress", "mysql", "-N", "-uwordpress", "wordpress", "-e"]
CLIENT_WARNING = "mysql: [Warning]"

ADMIN_IDS = (
    "SELECT user_id FROM wp_usermeta WHERE meta_key='wp_capabilities' "
    "AND meta_value LIKE '%administrator%';"
)
WATCHED_OPTIONS = (
    "SELECT option_name,option_value FROM wp_options "
    "WHERE option_name IN ('users_can_register','default_role');"
)
PUBLISHED_POSTS = (
    "SELECT ID FROM wp_posts WHERE post_status='publish' AND post_type='post';"
)


class StateUnavailable(RuntimeError):
    pass


def _rows(runner, sql: str) -> list[list[str]]:
    try:
        ran = runner(MYSQL + [sql], timeout=30.0)
    except Exception as exc:
        raise StateUnavailable(f"could not read corp-db: {exc}") from exc
    if not ran.ok:
        raise StateUnavailable(f"corp-db refused the query: {ran.output.strip()[:200]}")
    return [
        line.split("\t")
        for line in ran.output.splitlines()
        if line.strip() and not line.startswith(CLIENT_WARNING)
    ]


def snapshot(runner) -> dict:
    try:
        admins = [int(row[0]) for row in _rows(runner, ADMIN_IDS)]
        options = {row[0]: row[1] for row in _rows(runner, WATCHED_OPTIONS)}
        posts = [int(row[0]) for row in _rows(runner, PUBLISHED_POSTS)]
    except (ValueError, IndexError) as exc:
        raise StateUnavailable(f"corp-db returned an unreadable row: {exc}") from exc
    return {"admins": admins, "options": options, "posts": posts}


COLUMNS = {
    "wp_users": {"ID": 1, "user_login": 2},
    "wp_usermeta": {"user_id": 2, "meta_key": 3, "meta_value": 4},
    "wp_options": {"option_name": 2, "option_value": 3},
    "wp_posts": {"ID": 1, "post_author": 2, "post_content": 5, "post_title": 6, "post_status": 8},
}

_TIMESTAMP = re.compile(r"^SET TIMESTAMP=(\d+)")
_ROW = re.compile(r"^### (INSERT INTO|UPDATE|DELETE FROM) `[^`]+`\.`([A-Za-z0-9_]+)`")
_SECTION = re.compile(r"^### (SET|WHERE)$")
_COLUMN = re.compile(r"^###\s+@(\d+)=(.*)$")
_KIND = {"INSERT INTO": "insert", "UPDATE": "update", "DELETE FROM": "delete"}
_KEPT_SECTION = {"insert": "SET", "update": "SET", "delete": "WHERE"}


@dataclass(frozen=True)
class Change:
    table: str
    kind: str
    at: datetime
    columns: dict[int, str]


def _value(raw: str) -> str:
    raw = raw.strip()
    if raw.endswith("/* ... */"):
        raw = raw[: -len("/* ... */")].strip()
    if len(raw) >= 2 and raw[0] == "'" and raw[-1] == "'":
        return raw[1:-1]
    return raw


def parse_binlog(text: str, since: datetime | None = None) -> list[Change]:
    changes: list[Change] = []
    clock: datetime | None = None
    at: datetime | None = None
    table = kind = section = None
    columns: dict[int, str] = {}

    def flush():
        if table and kind and at is not None and columns:
            changes.append(Change(table=table, kind=kind, at=at, columns=dict(columns)))

    for line in text.splitlines():
        stamp = _TIMESTAMP.match(line)
        if stamp:
            clock = datetime.fromtimestamp(int(stamp.group(1)), tz=timezone.utc)
            continue
        head = _ROW.match(line)
        if head:
            flush()
            kind = _KIND[head.group(1)]
            table = head.group(2)
            at = clock
            section = None
            columns = {}
            continue
        part = _SECTION.match(line)
        if part and table:
            section = part.group(1)
            continue
        cell = _COLUMN.match(line)
        if cell and table and section == _KEPT_SECTION[kind]:
            columns[int(cell.group(1))] = _value(cell.group(2))
    flush()
    if since is not None:
        changes = [c for c in changes if c.at >= since]
    return changes

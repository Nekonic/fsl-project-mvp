from __future__ import annotations

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

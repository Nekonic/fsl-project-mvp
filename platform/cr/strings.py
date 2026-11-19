import json
import os
from functools import cache
from pathlib import Path

TABLE = "server.json"


def folder() -> Path:
    return Path(os.environ.get("CR_STRINGS_DIR") or Path(__file__).resolve().parents[2] / "strings")


@cache
def table() -> dict[str, str]:
    return json.loads((folder() / TABLE).read_text(encoding="utf-8"))


def line(key: str, **params: object) -> str:
    return table()[key].format(**params)

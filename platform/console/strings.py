import json
import re
from functools import cache
from pathlib import Path

TABLE = Path(__file__).resolve().parent / "templates/console/strings.html"
WITHHELD_FROM = "{% comment %}"

def parsed(source: str) -> dict[str, str]:
    block = source[source.index("= {") + 2:]
    depth = 0
    for end, character in enumerate(block):
        depth += (character == "{") - (character == "}")
        if depth == 0:
            break
    return json.loads(re.sub(r",(\s*})", r"\1", block[:end + 1]))

def shown() -> dict[str, str]:
    source = TABLE.read_text()
    return parsed(source[:source.index(WITHHELD_FROM)])

@cache
def withheld() -> dict[str, str]:
    source = TABLE.read_text()
    return parsed(source[source.index(WITHHELD_FROM):])

def line(key: str) -> str | None:
    return withheld().get(key)

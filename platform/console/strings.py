import json
import re
from functools import cache
from pathlib import Path

TABLE = Path(__file__).resolve().parent / "templates/console/strings.html"
LANGUAGES = ("en", "ko")
WITHHELD_FROM = "{% comment %}"

def parsed(source: str) -> dict[str, dict[str, str]]:
    found = {}
    for language in LANGUAGES:
        start = source.index(f"    {language}: {{")
        block = source[start + source[start:].index("{"):]
        depth = 0
        for end, character in enumerate(block):
            depth += (character == "{") - (character == "}")
            if depth == 0:
                break
        found[language] = json.loads(re.sub(r",(\s*})", r"\1", block[:end + 1]))
    return found

def shown() -> dict[str, dict[str, str]]:
    source = TABLE.read_text()
    return parsed(source[:source.index(WITHHELD_FROM)])

@cache
def withheld() -> dict[str, dict[str, str]]:
    source = TABLE.read_text()
    return parsed(source[source.index(WITHHELD_FROM):])

def both(key: str) -> dict[str, str]:
    return {language: table[key] for language, table in withheld().items() if key in table}

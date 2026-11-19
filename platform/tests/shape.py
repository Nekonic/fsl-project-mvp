import json
import re

ITEM_KEYS = {"path", "code", "line", "params"}
HANGUL = re.compile("[ᄀ-ᇿ㄰-㆏가-힣]")


def refusal(response) -> list[dict]:
    from cr import errors

    body = json.loads(response.content)
    assert set(body) == {"errors"}, body
    assert isinstance(body["errors"], list) and body["errors"], body
    for item in body["errors"]:
        assert set(item) <= ITEM_KEYS and {"path", "code"} <= set(item), item
        assert isinstance(item["path"], str) and item["code"] in errors.CODES, item
    assert not HANGUL.search(response.content.decode()), "the API sends codes, never Korean"
    return body["errors"]


def refused(response, status: int, code: str, path: str | None = None) -> dict:
    assert response.status_code == status, (response.status_code, response.content)
    found = [item for item in refusal(response) if item["code"] == code and (path is None or item["path"] == path)]
    assert found, (code, path, response.content)
    return found[0]

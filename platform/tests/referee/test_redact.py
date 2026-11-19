import json
import urllib.parse

from referee import service
from tests.referee.targets import TRUTH


def test_every_stored_hash_is_replaced_by_a_placeholder_of_the_same_length():
    dumped = json.dumps([{"username": name, "password": digest} for name, digest in TRUTH.items()])

    hidden = service.redact(dumped, TRUTH)

    assert len(hidden) == len(dumped)
    assert not any(digest in hidden for digest in TRUTH.values())
    assert all(name in hidden for name in TRUTH)


def test_a_hash_echoed_url_encoded_or_json_escaped_is_hidden_too():
    digest = TRUTH["minseo"]
    quoted = urllib.parse.quote(digest, safe="")
    escaped = json.dumps(digest)[1:-1].replace("/", "\\/")
    page = f"next={quoted}&q={urllib.parse.quote_plus(digest)} {json.dumps({'h': digest})} {escaped}"

    hidden = service.redact(page, TRUTH)

    assert len(hidden) == len(page)
    assert quoted not in hidden and urllib.parse.quote_plus(digest) not in hidden and digest not in hidden
    assert escaped not in hidden


def test_text_without_the_secret_comes_back_unchanged():
    page = "<html><body>No accounts here</body></html>"

    assert service.redact(page, TRUTH) == page
    assert service.redact(page, {}) == page


def test_a_baseline_with_no_stored_secret_hides_nothing():
    corp = {"admins": [1], "options": {"users_can_register": "0"}, "posts": [1]}
    page = "<p>[1]</p> {'users_can_register': '0'} 1"

    assert service.redact(page, corp) == page

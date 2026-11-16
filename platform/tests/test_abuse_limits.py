import json
import pathlib
import re

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from api import blocks, signin
from api.models import Session
from tests.conftest import ApiClient

pytestmark = pytest.mark.django_db

FRONT = pathlib.Path(__file__).resolve().parents[2] / "platform/nginx.conf"
ENTRYPOINT = FRONT.parent / "entrypoint.sh"


CHROME = {"HTTP_USER_AGENT": "Mozilla/5.0 Chrome/131", "HTTP_ACCEPT_LANGUAGE": "ko-KR"}
FIREFOX = {"HTTP_USER_AGENT": "Mozilla/5.0 Firefox/133", "HTTP_ACCEPT_LANGUAGE": "en-US"}


def signing_in(password, address="203.0.113.5", username="admin", browser=CHROME):
    return Client(REMOTE_ADDR=address, **browser).post(
        "/api/auth/login/", json.dumps({"username": username, "password": password}),
        content_type="application/json")


def signing_up(number, address="198.51.100.7"):
    return Client(REMOTE_ADDR=address).post("/api/auth/signup/", json.dumps({
        "username": f"learner{number}", "password": "range-practice-42", "password_confirm": "range-practice-42",
    }), content_type="application/json")


def test_three_failures_against_admin_block_that_address_and_not_the_account():
    answers = [signing_in("wrong") for _ in range(blocks.TIERS["staff"]["failures"])]
    blocked = signing_in("123456")
    elsewhere = signing_in("123456", address="198.51.100.20", browser=FIREFOX)

    assert [answer.status_code for answer in answers] == [401, 401, 429]
    assert blocked.status_code == 429 and blocked.json()["blocked_by"] == "address"
    assert 59 * 60 < int(blocked["Retry-After"]) <= 60 * 60
    assert elsewhere.status_code == 200, "nobody can lock admin out from another address"


def test_a_client_that_changes_address_but_keeps_its_headers_is_blocked_by_its_fingerprint():
    for number in range(blocks.TIERS["staff"]["failures"]):
        signing_in("wrong", address=f"203.0.113.{10 + number}")

    rotated = signing_in("123456", address="203.0.113.99")
    other_browser = signing_in("123456", address="203.0.113.98", browser=FIREFOX)

    assert rotated.status_code == 429 and rotated.json()["blocked_by"] == "fingerprint"
    assert other_browser.status_code == 200


def test_learner_names_take_ten_failures_and_the_platform_host_is_never_blocked():
    get_user_model().objects.create_user("learner1", password="range-practice-42")
    answers = [signing_in("wrong", username="learner1").status_code
               for _ in range(blocks.TIERS["learner"]["failures"])]
    from_the_vm = [signing_in("wrong", address="127.0.0.1").status_code for _ in range(5)]

    assert answers == [401] * 9 + [429]
    assert from_the_vm == [401] * 5
    assert signing_in("123456", address="127.0.0.1").status_code == 200


def test_a_successful_sign_in_forgets_the_failures_before_it():
    signing_in("wrong")
    signing_in("wrong")

    assert signing_in("123456").status_code == 200
    assert signing_in("wrong").status_code == 401


def test_an_admin_lists_and_lifts_a_block_and_a_learner_cannot(client):
    for _ in range(blocks.TIERS["staff"]["failures"]):
        signing_in("wrong")
    listed = client.get("/api/users/blocks/").json()["blocks"]
    address = next(block for block in listed if block["kind"] == "address")
    learner = ApiClient()
    learner.force_login(get_user_model().objects.create_user("learner1", password="range-practice-42"))

    assert address["value"] == "203.0.113.5" and address["username"] == "admin" and address["failures"] == 3
    assert learner.get("/api/users/blocks/").status_code == 403
    assert learner.post_json(f"/api/users/blocks/{address['id']}/unblock/").status_code == 403
    assert client.post_json(f"/api/users/blocks/{address['id']}/unblock/").status_code == 200
    assert signing_in("123456").status_code == 200


def test_one_address_signs_up_a_few_times_an_hour_and_no_more():
    made = [signing_up(number).status_code for number in range(signin.SIGN_UPS_PER_ADDRESS_PER_HOUR + 1)]

    assert made == [201] * signin.SIGN_UPS_PER_ADDRESS_PER_HOUR + [429]
    assert signing_up(99, address="198.51.100.8").status_code == 201


def test_sign_up_closes_while_the_pending_queue_is_full():
    get_user_model().objects.bulk_create(
        get_user_model()(username=f"waiting{number}", is_active=False) for number in range(signin.PENDING_AT_MOST)
    )

    answer = signing_up(1)

    assert answer.status_code == 503 and answer.json()["closed"] is True


def learner_client():
    learner = get_user_model().objects.create_user("learner1", password="range-practice-42")
    client = ApiClient()
    client.force_login(learner)
    return client, learner


def test_a_learner_holds_one_open_session_and_is_pointed_at_it():
    client, learner = learner_client()
    first = client.post_json("/api/sessions/", {})
    second = client.post_json("/api/sessions/", {})

    assert first.status_code == 201
    assert Session.objects.get(pk=first.json()["id"]).owner == learner
    assert second.status_code == 409 and second.json()["open_session"] == first.json()["id"]


def test_the_one_session_check_runs_again_where_the_slot_is_chosen():
    from api import views

    _, learner = learner_client()
    held = Session.objects.create(owner=learner)

    with pytest.raises(views.HoldsASession):
        views._opened_on_a_ready_slot(views.substrate(), {"owner": learner})
    assert Session.objects.filter(owner=learner).count() == 1 and held.ended_at is None


def test_an_admin_is_not_held_to_one_open_session(client):
    Session.objects.create(owner=get_user_model().objects.get(username="admin"))

    answer = client.post_json("/api/sessions/", {})

    assert "open_session" not in answer.json()


def location(opening):
    text = FRONT.read_text()
    start = text.index(opening)
    return text[start:text.index("\n        }", start)]


def test_the_front_limits_sign_in_sign_up_the_api_and_long_held_connections():
    text = FRONT.read_text()

    assert "limit_req zone=sign_in" in location("location = /api/auth/login/ {")
    assert "limit_req zone=sign_up" in location("location = /api/auth/signup/ {")
    api = location("location /api/ {")
    assert "limit_req zone=api_client" in api and "limit_req zone=api_address" in api
    for held in ("location /vm-terminal/kali/ {", "location /vm-terminal/waf/ {", "location ~ ^/site/"):
        assert "limit_conn held_open 10;" in location(held), held
    assert re.search(r"limit_req_zone \$limited_poster zone=sign_in:\S+ rate=5r/m;", text)
    assert "limit_req_status 429;" in text and "limit_conn_status 429;" in text


def test_the_platform_host_and_the_addresses_it_answers_as_are_not_throttled():
    geo = location("geo $from_the_platform_host {")

    assert "127.0.0.0/8 1;" in geo and "172.31.0.1 1;" in geo
    assert "include /tmp/nginx-platform-addresses.conf;" in geo
    entry = ENTRYPOINT.read_text()
    assert entry.index("/tmp/nginx-platform-addresses.conf") < entry.index("nginx -t")
    assert "DJANGO_ALLOWED_HOSTS" in entry

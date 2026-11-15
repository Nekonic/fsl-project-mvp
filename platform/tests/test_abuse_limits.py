import json
import pathlib
import re

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from api import signin
from api.models import Session
from tests.conftest import ApiClient

pytestmark = pytest.mark.django_db

FRONT = pathlib.Path(__file__).resolve().parents[2] / "platform/nginx.conf"
ENTRYPOINT = FRONT.parent / "entrypoint.sh"


def signing_in(password):
    return Client().post("/api/auth/login/", json.dumps({"username": "admin", "password": password}),
                         content_type="application/json")


def signing_up(number, address="198.51.100.7"):
    return Client(REMOTE_ADDR=address).post("/api/auth/signup/", json.dumps({
        "username": f"learner{number}", "password": "range-practice-42", "password_confirm": "range-practice-42",
    }), content_type="application/json")


def test_ten_wrong_passwords_lock_the_account_for_fifteen_minutes_even_against_the_right_one():
    answers = [signing_in("wrong") for _ in range(signin.FAILURES_BEFORE_LOCK)]
    locked = signing_in("123456")

    assert [answer.status_code for answer in answers[:-1]] == [401] * (signin.FAILURES_BEFORE_LOCK - 1)
    assert answers[-1].status_code == 429 and locked.status_code == 429
    assert locked.json()["locked_until"]
    assert 14 * 60 < int(locked["Retry-After"]) <= 15 * 60


def test_a_successful_sign_in_forgets_the_failures_before_it():
    for _ in range(signin.FAILURES_BEFORE_LOCK - 1):
        signing_in("wrong")

    assert signing_in("123456").status_code == 200
    assert signing_in("wrong").status_code == 401


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

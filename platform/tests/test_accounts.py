import json

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from tests.test_signin import signed_in_client

pytestmark = pytest.mark.django_db

LEARNER = {"username": "learner1", "password": "range-practice-42", "password_confirm": "range-practice-42"}


def sent(client, path, payload=None, token=None):
    return client.post(path, json.dumps(payload or {}), content_type="application/json",
                       **({"HTTP_X_CSRFTOKEN": token} if token else {}))


def signed_up(payload=LEARNER):
    client = Client(enforce_csrf_checks=True)
    token = client.get("/api/auth/").json()["csrf_token"]
    return sent(client, "/api/auth/signup/", payload, token)


def sign_in(username, password):
    client = Client()
    return client, sent(client, "/api/auth/login/", {"username": username, "password": password})


def admin():
    client, _ = signed_in_client()
    return client


def learner_id():
    return get_user_model().objects.get(username=LEARNER["username"]).pk


def test_a_sign_up_makes_an_inactive_learner_who_is_told_to_wait_for_approval():
    answer = signed_up()

    assert answer.status_code == 201 and answer.json()["pending"] is True
    made = get_user_model().objects.get(username="learner1")
    assert not made.is_active and not made.is_staff and made.check_password("range-practice-42")


def test_a_sign_up_without_the_csrf_token_is_refused():
    answer = sent(Client(enforce_csrf_checks=True), "/api/auth/signup/", LEARNER)

    assert answer.status_code == 403
    assert not get_user_model().objects.filter(username="learner1").exists()


@pytest.mark.parametrize("payload, code", [
    (LEARNER | {"password_confirm": "something-else-42"}, "password_mismatch"),
    (LEARNER | {"password": "1234", "password_confirm": "1234"}, "password_too_short"),
    (LEARNER | {"username": "admin"}, "unique"),
])
def test_a_sign_up_django_refuses_says_why_by_code(payload, code):
    answer = signed_up(payload)

    assert answer.status_code == 400
    assert code in [error["code"] for error in answer.json()["errors"]]
    assert get_user_model().objects.count() == 1


def test_a_pending_account_is_told_it_waits_and_is_not_signed_in():
    signed_up()
    client, answer = sign_in("learner1", "range-practice-42")
    _, wrong = sign_in("learner1", "not-the-password")

    assert answer.status_code == 403 and answer.json()["pending"] is True
    assert client.get("/api/sessions/").status_code == 401
    assert wrong.status_code == 401 and "pending" not in wrong.json()


def test_an_approved_learner_signs_in_and_is_not_staff():
    signed_up()
    approved = sent(admin(), f"/api/users/{learner_id()}/approve/")
    client, answer = sign_in("learner1", "range-practice-42")

    assert approved.status_code == 200 and approved.json()["active"] is True
    assert answer.status_code == 200 and answer.json()["staff"] is False
    assert client.get("/api/wargames/").status_code == 200


def test_a_rejected_sign_up_is_deleted_and_an_active_account_cannot_be_rejected():
    signed_up()
    staff = admin()
    rejected = sent(staff, f"/api/users/{learner_id()}/reject/")
    itself = sent(staff, f"/api/users/{get_user_model().objects.get(username='admin').pk}/reject/")

    assert rejected.status_code == 200
    assert not get_user_model().objects.filter(username="learner1").exists()
    assert itself.status_code == 409
    assert get_user_model().objects.get(username="admin").is_active


def test_the_admin_lists_accounts_and_a_learner_is_refused_every_account_route():
    signed_up()
    listed = admin().get("/api/users/").json()["users"]
    get_user_model().objects.filter(username="learner1").update(is_active=True)
    learner, _ = sign_in("learner1", "range-practice-42")

    assert [(user["username"], user["active"]) for user in listed] == [("learner1", False), ("admin", True)]
    assert learner.get("/api/users/").status_code == 403
    assert sent(learner, f"/api/users/{learner_id()}/approve/").status_code == 403
    assert sent(learner, f"/api/users/{learner_id()}/reject/").status_code == 403


def test_the_front_s_check_refuses_a_pending_account_even_with_a_session():
    signed_up()
    client = Client()
    client.force_login(get_user_model().objects.get(username="learner1"))

    assert client.get("/auth-check/").status_code == 401
    assert client.get("/auth-check/kibana/").status_code == 401


def test_the_login_page_links_to_sign_up_and_the_sign_up_page_posts_to_its_api():
    login = Client().get("/login/").content.decode()
    signup = Client().get("/signup/").content.decode()

    assert 'href="/signup/"' in login
    assert 'id="sign-up"' in signup and 'post("/api/auth/signup/"' in signup

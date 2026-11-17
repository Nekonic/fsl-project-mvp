import json

from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from api.models import Session
from tests.browser import open_page, worded
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


def approved_learner():
    signed_up()
    get_user_model().objects.filter(username=LEARNER["username"]).update(is_active=True)
    return learner_id()


def test_the_admin_deletes_an_approved_learner_and_keeps_their_closed_sessions():
    user_id = approved_learner()
    played = Session.objects.create(owner_id=user_id, ended_at="2026-11-16T00:00:00Z")

    answer = sent(admin(), f"/api/users/{user_id}/delete/")

    assert answer.status_code == 200 and answer.json()["deleted"] is True
    assert not get_user_model().objects.filter(pk=user_id).exists()
    played.refresh_from_db()
    assert played.owner is None


def test_deleting_a_learner_closes_their_open_session_through_the_close_path():
    user_id = approved_learner()
    held = Session.objects.create(owner_id=user_id)

    with patch("api.views.retention.prune_quietly") as close_ran:
        answer = sent(admin(), f"/api/users/{user_id}/delete/")

    held.refresh_from_db()
    assert answer.json()["closed_sessions"] == [held.pk]
    assert held.ended_at is not None and close_ran.called


def test_an_admin_account_cannot_be_deleted():
    other = get_user_model().objects.create_user("second-admin", password="range-practice-42", is_staff=True)

    answer = sent(admin(), f"/api/users/{other.pk}/delete/")

    assert answer.status_code == 409
    assert get_user_model().objects.filter(pk=other.pk).exists()


def test_an_admin_cannot_delete_their_own_account():
    itself = get_user_model().objects.get(username="admin").pk

    answer = sent(admin(), f"/api/users/{itself}/delete/")

    assert answer.status_code == 409 and "own" in answer.json()["detail"]
    assert get_user_model().objects.filter(pk=itself).exists()


def test_the_admin_lists_accounts_and_a_learner_is_refused_every_account_route():
    signed_up()
    listed = admin().get("/api/users/").json()["users"]
    get_user_model().objects.filter(username="learner1").update(is_active=True)
    learner, _ = sign_in("learner1", "range-practice-42")

    assert [(user["username"], user["active"]) for user in listed] == [("learner1", False), ("admin", True)]
    assert learner.get("/api/users/").status_code == 403
    assert sent(learner, f"/api/users/{learner_id()}/approve/").status_code == 403
    assert sent(learner, f"/api/users/{learner_id()}/reject/").status_code == 403
    assert sent(learner, f"/api/users/{learner_id()}/delete/").status_code == 403


def test_the_front_s_check_refuses_a_pending_account_even_with_a_session():
    signed_up()
    client = Client()
    client.force_login(get_user_model().objects.get(username="learner1"))

    assert client.get("/auth-check/").status_code == 401


def test_the_login_page_links_to_sign_up_and_the_sign_up_page_posts_to_its_api():
    login = Client().get("/login/").content.decode()
    signup = Client().get("/signup/").content.decode()

    assert 'href="/signup/"' in login
    assert 'id="sign-up"' in signup and 'post("/api/auth/signup/"' in signup


def test_a_deleted_account_s_row_says_it_is_being_deleted_until_the_api_answers():
    seen = open_page(admin(), "/users/", setup="""
      confirm = () => true;
      let answered = null;
      browser.serve((request) => {
        if (request.route === "/api/users/") {
          return {body: {users: [{id: 7, username: "learner1", active: true, staff: false, joined: "2026-11-01T00:00:00Z"}]}};
        }
        if (request.route === "/api/users/7/delete/") return new Promise((resolve) => { answered = () => resolve({body: {}}); });
        return {body: {blocks: []}};
      });
      window.answer = () => answered();
    """, scenario="""
      const button = document.querySelector('[data-delete="7"]');
      const row = button.closest('tr');
      browser.element('active').dispatchEvent({type: 'click', target: button});
      await browser.settle();
      const pending = {disabled: button.disabled, text: button.textContent, busy: row.getAttribute('aria-busy')};
      window.answer();
      await browser.settle();
      return pending;
    """)

    assert seen["errors"] == []
    assert seen["result"] == {"disabled": True, "text": worded("users.deleting"), "busy": "true"}


@pytest.mark.parametrize("action, said", [("approve", "users.approving"), ("reject", "users.rejecting")])
def test_an_approved_or_rejected_sign_up_s_row_says_so_until_the_api_answers(action, said):
    seen = open_page(admin(), "/users/", setup="""
      let answered = null;
      browser.serve((request) => {
        if (request.route === "/api/users/") {
          return {body: {users: [{id: 8, username: "learner2", active: false, staff: false, joined: "2026-11-01T00:00:00Z"}]}};
        }
        if (request.route.startsWith("/api/users/8/")) return new Promise((resolve) => { answered = () => resolve({body: {}}); });
        return {body: {blocks: []}};
      });
      window.answer = () => answered();
    """, scenario="""
      const button = document.querySelector('[data-ACTION="8"]');
      const row = button.closest('tr');
      browser.element('pending').dispatchEvent({type: 'click', target: button});
      await browser.settle();
      const shown = {text: button.textContent, busy: row.getAttribute('aria-busy'),
                     disabled: row.querySelectorAll('button').map((one) => one.disabled)};
      window.answer();
      await browser.settle();
      return shown;
    """.replace("ACTION", action))

    assert seen["errors"] == []
    assert seen["result"] == {"text": worded(said), "busy": "true", "disabled": [True, True]}, (
        "the other button of the row would send a second decision while the first is pending")

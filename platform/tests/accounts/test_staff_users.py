from rest_framework.test import APIClient

from tests.conftest import CALLER, PASSWORD
from tests.shape import refused


def test_staff_list_accounts_with_the_waiting_ones_first(as_staff, make_user):
    make_user("waiting", active=False)

    listed = as_staff.get("/api/staff/users/").json()

    assert listed[0]["username"] == "waiting" and listed[0]["approved"] is False
    assert {"operator", "waiting"} <= {account["username"] for account in listed}
    assert set(listed[0]) == {"id", "username", "approved", "is_staff", "joined"}


def test_a_learner_and_a_stranger_are_refused_the_staff_routes(browser, as_learner):
    refused(as_learner.get("/api/staff/users/"), 403, "not_staff")
    refused(APIClient().get("/api/staff/users/"), 401, "not_signed_in")


def test_approving_an_unknown_account_is_not_found(as_staff):
    refused(as_staff.post("/api/staff/users/999/approve/"), 404, "unknown_user")


def test_disabling_an_account_ends_its_session_and_its_sign_in(as_staff, learner):
    signed_in = APIClient(REMOTE_ADDR=CALLER)
    assert signed_in.login(username="learner", password=PASSWORD)
    assert signed_in.get("/api/me/").status_code == 200

    assert as_staff.post(f"/api/staff/users/{learner.pk}/disable/").json()["approved"] is False

    refused(signed_in.get("/api/me/"), 401, "not_signed_in")
    refused(signed_in.post("/api/auth/login/", {"username": "learner", "password": PASSWORD}, format="json"),
            403, "account_pending")


def test_staff_cannot_disable_their_own_account(as_staff, staff):
    refused(as_staff.post(f"/api/staff/users/{staff.pk}/disable/"), 409, "own_account")

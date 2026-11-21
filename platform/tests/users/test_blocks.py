from rest_framework.test import APIClient

from tests.conftest import PASSWORD
from tests.shape import refused
from users import blocks

WRONG = "wrong-password-0"


def attempt(browser, username, password=WRONG, address=None):
    extra = {"REMOTE_ADDR": address} if address else {}
    return browser.post("/api/auth/login/", {"username": username, "password": password}, format="json", **extra)


def fail(browser, username, times, address=None):
    return [attempt(browser, username, address=address) for _ in range(times)][-1]


def test_a_learner_address_is_blocked_after_ten_failures_even_for_the_right_password(browser, learner):
    last = fail(browser, "learner", blocks.TIERS["learner"]["failures"])

    found = refused(last, 429, "sign_in_blocked")
    assert found["params"]["by"] == "address" and found["params"]["until"]
    assert 0 < int(last["Retry-After"]) <= blocks.TIERS["learner"]["blocked_for"]
    refused(attempt(browser, "learner", PASSWORD), 429, "sign_in_blocked")


def test_a_staff_username_is_blocked_after_its_tier_s_failures(browser, staff):
    assert fail(browser, "operator", blocks.TIERS["staff"]["failures"] - 1).status_code == 401

    refused(attempt(browser, "operator"), 429, "sign_in_blocked")


def test_the_platform_host_is_never_blocked(browser, learner):
    fail(browser, "learner", 12, address="127.0.0.1")

    assert attempt(browser, "learner", PASSWORD, address="127.0.0.1").status_code == 200


def test_a_success_clears_the_address_count(browser, learner):
    fail(browser, "learner", blocks.TIERS["learner"]["failures"] - 1)
    assert attempt(browser, "learner", PASSWORD).status_code == 200

    assert attempt(browser, "learner").status_code == 401


def test_one_browser_failing_from_two_addresses_is_blocked_by_fingerprint_from_a_third(browser, learner):
    limit = blocks.TIERS["learner"]["failures"]
    fail(browser, "learner", limit // 2, address="198.51.100.1")
    fail(browser, "learner", limit - limit // 2, address="198.51.100.2")

    found = refused(attempt(browser, "learner", PASSWORD, address="198.51.100.3"), 429, "sign_in_blocked")
    assert found["params"]["by"] == "fingerprint"


def test_staff_list_the_standing_blocks_and_lift_one(browser, staff, learner):
    fail(browser, "learner", blocks.TIERS["learner"]["failures"])
    desk = APIClient()
    desk.force_authenticate(staff)

    listed = desk.get("/api/staff/blocks/").json()
    assert [(block["kind"], block["username"], block["failures"]) for block in listed] == [("address", "learner", 10)]

    assert desk.delete(f"/api/staff/blocks/{listed[0]['id']}/").status_code == 204
    assert desk.get("/api/staff/blocks/").json() == []
    assert attempt(browser, "learner").status_code == 401
    assert attempt(browser, "learner", PASSWORD).status_code == 200


def test_lifting_a_block_that_is_gone_is_not_found(as_staff):
    refused(as_staff.delete("/api/staff/blocks/999/"), 404, "unknown_block")


def test_a_learner_cannot_see_the_blocks(as_learner):
    refused(as_learner.get("/api/staff/blocks/"), 403, "not_staff")

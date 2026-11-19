import pytest
from django.test import Client, override_settings
from rest_framework import exceptions, serializers
from rest_framework.test import APIClient

from accounts import blocks, signin
from cr import errors, handler
from tests.conftest import CALLER
from tests.shape import refused


def wrong_sign_in(browser):
    return browser.post("/api/auth/login/", {"username": "operator", "password": "wrong-password-0"}, format="json")


def blocked(browser, staff):
    for _ in range(blocks.TIERS["staff"]["failures"]):
        answer = wrong_sign_in(browser)
    return answer


def strict_sign_in(browser, staff):
    return APIClient(enforce_csrf_checks=True, REMOTE_ADDR=CALLER).post(
        "/api/auth/login/", {"username": "operator", "password": "x"}, format="json")


def closed_sign_up(browser, staff, monkeypatch):
    monkeypatch.setattr(signin, "PENDING_AT_MOST", 0)
    return browser.post("/api/auth/signup/", {"username": "late", "password": "violet-harbour-1187"}, format="json")


def own_disable(browser, staff):
    browser.force_authenticate(staff)
    return browser.post(f"/api/staff/users/{staff.pk}/disable/")


def as_staff(browser, staff, call):
    browser.force_authenticate(staff)
    return call(browser)


def as_learner_listing(browser):
    from django.contrib.auth import get_user_model

    browser.force_authenticate(get_user_model().objects.create_user(username="plain", password="x"))
    return browser.get("/api/staff/users/")


REFUSAL_PATHS = {
    "unknown route": (404, "not_found", lambda browser, staff, mp: browser.get("/api/nowhere/")),
    "route without its slash": (404, "not_found", lambda browser, staff, mp: browser.get("/api/me")),
    "wrong method": (405, "method_not_allowed", lambda browser, staff, mp: browser.get("/api/auth/login/")),
    "not signed in": (401, "not_signed_in", lambda browser, staff, mp: browser.get("/api/me/")),
    "not staff": (403, "not_staff", lambda browser, staff, mp: as_learner_listing(browser)),
    "no csrf token": (403, "csrf_failed", lambda browser, staff, mp: strict_sign_in(browser, staff)),
    "malformed json": (400, "malformed", lambda browser, staff, mp: browser.post(
        "/api/auth/login/", "{not json", content_type="application/json")),
    "not json": (415, "unsupported_media_type", lambda browser, staff, mp: browser.post(
        "/api/auth/login/", "username=a", content_type="application/x-www-form-urlencoded")),
    "missing field": (400, "required", lambda browser, staff, mp: browser.post("/api/auth/login/", {}, format="json")),
    "wrong password": (401, "wrong_credentials", lambda browser, staff, mp: wrong_sign_in(browser)),
    "unknown user": (404, "unknown_user", lambda browser, staff, mp: as_staff(
        browser, staff, lambda signed: signed.post("/api/staff/users/999/approve/"))),
    "own account": (409, "own_account", lambda browser, staff, mp: own_disable(browser, staff)),
    "sign-in blocked": (429, "sign_in_blocked", lambda browser, staff, mp: blocked(browser, staff)),
    "sign-up closed": (503, "sign_ups_closed", lambda browser, staff, mp: closed_sign_up(browser, staff, mp)),
    "bad cursor": (400, "invalid", lambda browser, staff, mp: as_staff(
        browser, staff, lambda signed: signed.get(f"/api/rounds/{a_round().pk}/events/?after=x"))),
    "unknown round": (404, "unknown_round", lambda browser, staff, mp: as_staff(
        browser, staff, lambda signed: signed.get("/api/rounds/999/events/"))),
}


def a_round():
    from tests import rounds

    return rounds.opened(rounds.problem())


@pytest.mark.parametrize("name", sorted(REFUSAL_PATHS))
def test_every_refusal_path_answers_in_the_one_error_shape(browser, staff, monkeypatch, name):
    status, code, call = REFUSAL_PATHS[name]

    found = refused(call(browser, staff, monkeypatch), status, code)

    assert status == next(kind.status for kind in errors.KINDS if found["code"] in kind.codes)


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="tests.contract.broken_urls")
def test_a_bug_answers_in_the_error_shape_too():
    refused(Client(raise_request_exception=False).get("/broken/"), 500, "server_error")


@pytest.mark.parametrize("kind", errors.KINDS)
def test_the_handler_maps_every_domain_error_to_its_status(kind):
    answer = handler.handle(kind(), {})

    assert answer.status_code == kind.status
    assert answer.data == {"errors": [{"path": "", "code": kind.code}]}


@pytest.mark.parametrize("raised, status, code", [
    (ValueError("bad"), 400, "invalid"),
    (PermissionError("no"), 403, "not_seated"),
    (exceptions.Throttled(wait=4.2), 429, "too_many"),
    (exceptions.PermissionDenied(code="not_staff"), 403, "not_staff"),
    (exceptions.PermissionDenied(code="something_else"), 403, "not_seated"),
])
def test_the_handler_maps_python_and_drf_refusals(raised, status, code):
    answer = handler.handle(raised, {})

    assert answer.status_code == status and answer.data["errors"][0]["code"] == code


def test_a_throttle_says_when_to_retry():
    assert handler.handle(exceptions.Throttled(wait=4.2), {})["Retry-After"] == "5"


def test_an_unexpected_exception_is_left_to_the_server_error_view():
    assert handler.handle(RuntimeError("bug"), {}) is None


class Check(serializers.Serializer):
    case = serializers.CharField()


class Step(serializers.Serializer):
    check = serializers.DictField(child=Check())


class Document(serializers.Serializer):
    title = serializers.CharField()
    steps = Step(many=True)


def test_nested_field_errors_come_back_by_drf_style_path():
    document = Document(data={"steps": [{"check": {"params": {"case": "x"}}}] * 3 + [{"check": {"params": {}}}]})
    document.is_valid()

    answer = handler.handle(exceptions.ValidationError(document.errors), {})

    assert answer.status_code == 400
    assert answer.data["errors"] == [{"path": "title", "code": "required"},
                                     {"path": "steps[3].check.params.case", "code": "required"}]


def test_every_code_belongs_to_exactly_one_kind():
    named = [code for kind in errors.KINDS for code in kind.codes]

    assert len(named) == len(set(named))

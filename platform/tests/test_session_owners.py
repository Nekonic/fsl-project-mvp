import pathlib
from datetime import datetime, timezone

import pytest
from django.contrib.auth import get_user_model

from api.models import Detection, Session
from tests.conftest import ApiClient

pytestmark = pytest.mark.django_db

FRONT = pathlib.Path(__file__).resolve().parents[2] / "platform/nginx.conf"


def learner(name):
    user = get_user_model().objects.create_user(name, password="range-practice-42")
    client = ApiClient()
    client.force_login(user)
    return client, user


@pytest.fixture
def two_learners():
    mine, me = learner("learner1")
    _, other = learner("learner2")
    return mine, Session.objects.create(owner=me), Session.objects.create(owner=other)


def test_a_learner_lists_only_their_own_sessions_and_an_admin_lists_all(client, two_learners):
    mine, own, others = two_learners

    assert [row["id"] for row in mine.get("/api/sessions/").json()] == [own.pk]
    assert {own.pk, others.pk} <= {row["id"] for row in client.get("/api/sessions/").json()}


def test_a_learner_cannot_read_drive_or_open_another_learner_s_session(two_learners):
    mine, own, others = two_learners
    detection = Detection.objects.create(session=others, detection_id="d1", source="suricata", signature="x",
                                         timestamp=datetime(2026, 11, 16, tzinfo=timezone.utc))

    for path in (f"/api/sessions/{others.pk}/", f"/api/sessions/{others.pk}/score/",
                 f"/api/sessions/{others.pk}/map/", f"/api/detections/{detection.pk}/"):
        assert mine.get(path).status_code == 404, path
    assert mine.post_json(f"/api/sessions/{others.pk}/close/").status_code == 404
    assert mine.get(f"/blue/{others.pk}/").status_code == 404
    assert mine.get(f"/api/rules/?session={others.pk}").status_code == 404
    assert Session.objects.get(pk=others.pk).ended_at is None
    assert mine.get(f"/api/sessions/{own.pk}/").status_code == 200


def test_a_learner_who_names_no_session_acts_on_their_own_not_the_newest(two_learners):
    from django.test import RequestFactory

    from api import views

    _, own, others = two_learners
    asking = RequestFactory().get("/api/rules/")
    asking.user = own.owner

    assert others.pk > own.pk
    assert views._asked_session(asking) == own
    nobody, _ = learner("learner3")
    assert nobody.get("/api/rules/").status_code == 409


def test_only_an_admin_changes_the_range(two_learners):
    mine, _, _ = two_learners

    assert mine.post_json("/api/range/slot/rebuild/").status_code == 403
    assert mine.post_json("/api/range/configure/").status_code == 403
    assert mine.post_json("/api/range/fabric/").status_code == 403


@pytest.mark.parametrize("uri, theirs", [
    ("/site/{own}/board.com/", 204),
    ("/site/{others}/board.com/", 403),
    ("/vm-terminal/kali/?arg={own}", 204),
    ("/vm-terminal/kali/ws?arg={own}", 204),
    ("/vm-terminal/waf/?arg={others}", 403),
    ("/vm-terminal/kali/?arg={others}&arg={own}", 403),
    ("/vm-terminal/kali/", 403),
    ("/kibana/app/discover", 204),
])
def test_the_front_s_check_opens_a_learner_s_own_session_only(client, two_learners, uri, theirs):
    mine, own, others = two_learners
    asked = uri.format(own=own.pk, others=others.pk)

    assert mine.get("/auth-check/", HTTP_X_ORIGINAL_URI=asked).status_code == theirs
    assert client.get("/auth-check/", HTTP_X_ORIGINAL_URI=asked).status_code == 204


def test_the_front_s_cache_tells_sessions_and_terminals_apart():
    text = FRONT.read_text()

    assert "~^/site/(?<asked_site>\\d+)/ site:$asked_site;" in text
    assert "~^/vm-terminal/[^?]*\\?(?<asked_query>.*)$ terminal:$asked_query;" in text
    assert "~^/vm-terminal/ terminal:;" in text

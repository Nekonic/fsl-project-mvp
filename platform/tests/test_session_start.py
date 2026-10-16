from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from api.models import Session
from range import slot

pytestmark = pytest.mark.django_db

class Cloud:
    def plan_slot(self):
        return slot.Plan(standing=(("fsl-waf", "s1", "ACTIVE"),))

    def runner(self, role):
        return lambda *a, **k: None

def _verdict(ready, blocked=()):
    return {
        "ready": ready,
        "substrate": "openstack",
        "slot": {"phase": "READY" if ready else "CHECKING",
                 "standing": [], "checks": {}, "blocked": list(blocked)},
    }

class Shared:
    def runner(self, role):
        return lambda *a, **k: None

def test_starting_refuses_a_second_open_session_on_a_shared_range(client):
    with patch("api.views.substrate", lambda: Shared()):
        first = client.post_json("/api/sessions/", {})
        second = client.post_json("/api/sessions/", {})

    assert first.status_code == 201
    assert second.status_code == 409, (
        "a range with one target for every session would score the second "
        "session against the first one's traffic"
    )
    assert "already open" in second.json()["detail"]
    assert Session.objects.filter(ended_at=None).count() == 1

def test_docker_opens_a_second_session_beside_the_open_one(client):
    opened = []

    def open_session(self, session_id, live=()):
        opened.append((session_id, list(live)))

    with patch("range.docker.Docker.open_session", open_session):
        first = client.post_json("/api/sessions/", {})
        second = client.post_json("/api/sessions/", {})

    assert (first.status_code, second.status_code) == (201, 201), second.content
    assert Session.objects.filter(ended_at=None).count() == 2
    assert opened == [
        (first.json()["id"], []),
        (second.json()["id"], [first.json()["id"]]),
    ], "the stack of the session still open was not kept"

def test_starting_refuses_a_slot_that_is_not_ready(client):
    with patch("api.views.substrate", lambda: Cloud()), patch(
        "api.views._range_ready", return_value=_verdict(False, ["fsl-waf is REBUILD"])
    ):
        response = client.post_json("/api/sessions/", {})

    assert response.status_code == 409
    assert "fsl-waf is REBUILD" in response.json()["detail"]
    assert Session.objects.count() == 0, "a not-ready start must create no row"

def test_starting_refuses_a_second_open_session_on_the_cloud(client):
    Session.objects.create(scenario="board", baseline=[])
    with patch("api.views.substrate", lambda: Cloud()), patch(
        "api.views._range_ready", return_value=_verdict(True)
    ):
        response = client.post_json("/api/sessions/", {})

    assert response.status_code == 409
    assert "already open" in response.json()["detail"]
    assert Session.objects.count() == 1

def test_docker_refuses_a_session_past_its_cap(client):
    with patch("range.docker.Docker.open_session", lambda self, session_id, live=(): None):
        answers = [client.post_json("/api/sessions/", {}) for _ in range(3)]

    assert [a.status_code for a in answers] == [201, 201, 409], (
        "every open session keeps a whole stack up, and past the cap the host "
        "runs out of memory and Elasticsearch dies first"
    )
    assert answers[2].json()["detail"] == (
        "2 sessions are already open on the range; close one first"
    )
    assert Session.objects.filter(ended_at=None).count() == 2

def test_closing_a_session_frees_a_place_under_the_cap(client):
    with patch("range.docker.Docker.open_session", lambda self, session_id, live=(): None):
        first, _ = [client.post_json("/api/sessions/", {}).json()["id"] for _ in range(2)]
        client.post_json(f"/api/sessions/{first}/close/", {})
        third = client.post_json("/api/sessions/", {})

    assert third.status_code == 201, third.content

def test_an_openstack_session_starts_with_the_attacker_at_the_front_door(client):
    aimed = []

    with patch("api.views.substrate", lambda: Cloud()), patch(
        "api.views._range_ready", return_value=_verdict(True)
    ), patch("api.views.loot.ground_truth", return_value={}), patch(
        "api.views._aim_attacker", lambda adapter: aimed.append(adapter)
    ):
        opened = client.post_json("/api/sessions/", {})

    assert opened.status_code == 201
    assert len(aimed) == 1, (
        "the rebuilt attacker box leaves from whichever address DHCP made primary, "
        "not the declared default origin, so an attack sent with no origin is "
        "placed somewhere the range never chose"
    )

def test_docker_keeps_the_stack_of_a_session_closed_moments_ago(client):
    opened = []
    now = timezone.now()
    shipping = Session.objects.create(scenario="board", baseline=[],
                                      ended_at=now - timedelta(seconds=30))
    shipped = Session.objects.create(scenario="board", baseline=[],
                                     ended_at=now - timedelta(hours=1))

    def open_session(self, session_id, live=()):
        opened.append(list(live))

    with patch("range.docker.Docker.open_session", open_session):
        answer = client.post_json("/api/sessions/", {})

    assert answer.status_code == 201, answer.content
    assert opened == [[shipping.pk]], (
        "a stack taken down the moment its session closes loses the alerts its "
        "Filebeat has not shipped yet, and that session is scored without them; "
        f"kept {opened}, closed an hour ago: {shipped.pk}"
    )

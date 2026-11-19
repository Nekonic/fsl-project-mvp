from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory, force_authenticate
from rest_framework.views import APIView

from match import auth
from tests import rounds

pytestmark = pytest.mark.django_db


class AttackRoute(APIView):
    authentication_classes = auth.ROUND_AUTHENTICATION
    permission_classes = [auth.HasSeat("attack")]

    def get(self, request, round_id):
        return Response({"seat": request.seat.pk})

    def post(self, request, round_id):
        return Response({"seat": request.seat.pk})


class DefenceRoute(AttackRoute):
    permission_classes = [auth.HasSeat("defence")]


class RoundRoute(APIView):
    authentication_classes = auth.ROUND_AUTHENTICATION
    permission_classes = [auth.InRound]

    def get(self, request, round_id):
        return Response({"seats": [seat.side for seat in request.seats], "operator": request.operator})


class LeaseRoute(APIView):
    authentication_classes = auth.ROUND_AUTHENTICATION
    permission_classes = [auth.IsOperator]

    def post(self, request, lease_id):
        return Response({"lease": request.lease.pk})


def called(route, *, method="get", token=None, user=None, csrf=False, **kwargs):
    factory = APIRequestFactory(enforce_csrf_checks=csrf)
    headers = {"HTTP_AUTHORIZATION": f"Bearer {token}"} if token else {}
    request = getattr(factory, method)("/", format="json", **headers)
    if user is not None:
        force_authenticate(request, user=user)
    answer = route.as_view()(request, **kwargs)
    answer.render()
    return answer


def codes(answer):
    return [error["code"] for error in answer.data["errors"]]


@pytest.fixture
def bot_round():
    found = rounds.opened(rounds.problem())
    seat = rounds.seated(found, "attack", bot_name="attack-bot")
    return found, seat, auth.issue_token(seat)


def test_a_bot_token_reaches_its_own_side_of_its_own_round(bot_round):
    found, seat, token = bot_round

    answer = called(AttackRoute, method="post", token=token, csrf=True, round_id=found.pk)

    assert answer.status_code == 200 and answer.data == {"seat": seat.pk}


def test_a_bot_token_does_not_reach_the_other_side_or_another_round(bot_round):
    found, _, token = bot_round
    other = rounds.opened(rounds.problem())
    rounds.seated(other, "attack", bot_name="another-bot")

    assert codes(called(DefenceRoute, token=token, round_id=found.pk)) == ["not_seated"]
    assert codes(called(AttackRoute, token=token, round_id=other.pk)) == ["not_seated"]


def test_the_token_is_stored_only_as_its_hash(bot_round):
    _, seat, token = bot_round
    seat.refresh_from_db()

    assert seat.token_hash == auth.hashed(token) and token not in seat.token_hash


def test_an_unknown_malformed_or_revoked_token_is_not_signed_in(bot_round):
    found, seat, token = bot_round

    assert codes(called(AttackRoute, token="not-a-token", round_id=found.pk)) == ["not_signed_in"]
    assert codes(called(AttackRoute, token="\xff\xfe", round_id=found.pk)) == ["not_signed_in"]
    assert called(AttackRoute, token=f"{token} extra", round_id=found.pk).status_code == 401
    auth.revoke_token(seat)
    revoked = called(AttackRoute, token=token, round_id=found.pk)
    assert codes(revoked) == ["not_signed_in"]
    assert revoked["WWW-Authenticate"] == 'Bearer realm="seat"'


def test_after_the_end_a_token_reads_for_fifteen_minutes_and_writes_nothing(bot_round):
    found, _, token = bot_round
    found.phase, found.ended = "ended", timezone.now() - timedelta(minutes=10)
    found.save()

    assert called(AttackRoute, token=token, round_id=found.pk).status_code == 200
    assert codes(called(AttackRoute, method="post", token=token, round_id=found.pk)) == ["round_closed"]

    found.ended = timezone.now() - timedelta(minutes=16)
    found.save()
    assert codes(called(AttackRoute, token=token, round_id=found.pk)) == ["not_signed_in"]


@pytest.mark.parametrize("phase", ["created", "starting"])
def test_a_write_before_the_round_runs_is_refused_and_a_read_is_not(make_user, phase):
    player = make_user("player")
    found = rounds.opened(rounds.problem(), phase=phase)
    rounds.seated(found, "defence", user=player)

    refused = called(DefenceRoute, method="post", user=player, round_id=found.pk)

    assert refused.status_code == 409 and codes(refused) == ["round_not_started"]
    assert called(DefenceRoute, user=player, round_id=found.pk).status_code == 200


def test_a_signed_in_user_reaches_only_the_seat_they_hold(make_user):
    player, outsider = make_user("player"), make_user("outsider")
    found = rounds.opened(rounds.problem())
    rounds.seated(found, "defence", user=player)

    assert called(DefenceRoute, user=player, round_id=found.pk).status_code == 200
    assert codes(called(AttackRoute, user=player, round_id=found.pk)) == ["not_seated"]
    assert codes(called(DefenceRoute, user=outsider, round_id=found.pk)) == ["not_seated"]
    assert codes(called(DefenceRoute, round_id=found.pk)) == ["not_signed_in"]


def test_a_lesson_learner_holds_both_seats(make_user):
    learner = make_user("student")
    found = rounds.opened(rounds.lesson_problem())
    rounds.seated(found, "attack", user=learner)
    rounds.seated(found, "defence", user=learner)

    assert called(AttackRoute, user=learner, round_id=found.pk).status_code == 200
    assert called(DefenceRoute, user=learner, round_id=found.pk).status_code == 200
    assert called(RoundRoute, user=learner, round_id=found.pk).data == {"seats": ["attack", "defence"],
                                                                        "operator": False}


def test_an_unknown_round_is_not_found(make_user):
    assert codes(called(AttackRoute, user=make_user("player"), round_id=999)) == ["unknown_round"]


def test_the_round_reads_admit_its_seats_and_its_operator_and_no_one_else(make_user, staff, bot_round):
    opener, outsider = make_user("opener"), make_user("outsider")
    found = rounds.opened(rounds.problem(), opened_by=opener)
    seat = rounds.seated(found, "attack", bot_name="attack-bot")
    token = auth.issue_token(seat)

    assert called(RoundRoute, user=opener, round_id=found.pk).data == {"seats": [], "operator": True}
    assert called(RoundRoute, user=staff, round_id=found.pk).data["operator"] is True
    assert called(RoundRoute, token=token, round_id=found.pk).data == {"seats": ["attack"], "operator": False}
    assert codes(called(RoundRoute, user=outsider, round_id=found.pk)) == ["not_seated"]
    assert codes(called(RoundRoute, token=bot_round[2], round_id=found.pk)) == ["not_seated"]


def test_only_the_lease_s_opener_or_staff_operate_it(make_user, staff, bot_round):
    opener, player = make_user("opener"), make_user("player")
    found = rounds.opened(rounds.problem(), opened_by=opener)
    rounds.seated(found, "attack", user=player)
    lease = found.lease.pk

    assert called(LeaseRoute, method="post", user=opener, lease_id=lease).data == {"lease": lease}
    assert called(LeaseRoute, method="post", user=staff, lease_id=lease).status_code == 200
    assert codes(called(LeaseRoute, method="post", user=player, lease_id=lease)) == ["not_operator"]
    assert codes(called(LeaseRoute, method="post", token=bot_round[2], lease_id=bot_round[0].lease.pk)) == [
        "not_operator"]
    assert codes(called(LeaseRoute, method="post", user=opener, lease_id=9999)) == ["unknown_lease"]


def test_a_seat_side_that_does_not_exist_is_a_programming_error():
    with pytest.raises(ValueError):
        auth.HasSeat("referee")

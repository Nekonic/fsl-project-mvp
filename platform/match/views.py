import json
from dataclasses import asdict

from drf_spectacular.utils import extend_schema
from rest_framework import renderers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts import service as accounts
from match import auth, serializers, service

TAGS = ["match"]
STAFF_TAGS = ["staff"]


def given(serializer, data):
    checked = serializer(data=data)
    checked.is_valid(raise_exception=True)
    return checked.validated_data


def shown_lease(held, serializer=serializers.LeaseShown):
    held.ready = service.ready(held)
    return serializer(held).data


class MatchView(APIView):
    authentication_classes = auth.ROUND_AUTHENTICATION


class Leases(MatchView):
    permission_classes = [auth.Approved]

    @extend_schema(tags=TAGS, request=serializers.OpenLease, responses={201: serializers.LeaseShown},
                   operation_id="lease_open")
    def post(self, request):
        held = service.open_lease(request.user, given(serializers.OpenLease, request.data)["wargame"])
        return Response(shown_lease(held), status=status.HTTP_201_CREATED)


class Lease(MatchView):
    permission_classes = [auth.IsOperator]

    @extend_schema(tags=TAGS, responses=serializers.LeaseDetail, operation_id="lease_read")
    def get(self, request, lease_id: int):
        return Response(shown_lease(request.lease, serializers.LeaseDetail))


class Heartbeat(MatchView):
    permission_classes = [auth.OnLease]

    @extend_schema(tags=TAGS, request=None, responses=serializers.Expiry, operation_id="lease_heartbeat")
    def post(self, request, lease_id: int):
        return Response(serializers.Expiry(service.heartbeat(request.lease)).data)


class CloseLease(MatchView):
    permission_classes = [auth.IsOperator]

    @extend_schema(tags=TAGS, request=None, responses=serializers.Closed, operation_id="lease_close")
    def post(self, request, lease_id: int):
        return Response(serializers.Closed(service.close_lease(request.lease)).data)


class LeaseRounds(MatchView):
    permission_classes = [auth.IsOperator]

    @extend_schema(tags=TAGS, request=serializers.CreateRound, responses={201: serializers.Created},
                   operation_id="round_create")
    def post(self, request, lease_id: int):
        asked = given(serializers.CreateRound, request.data)
        made = service.create_round(request.lease, asked["problem"], asked["matchup"], dict(asked["seats"]))
        return Response(serializers.Created(made).data, status=status.HTTP_201_CREATED)


class Rounds(MatchView):
    permission_classes = [auth.Approved]

    @extend_schema(tags=TAGS, parameters=[serializers.RoundsQuery], responses=serializers.RoundLine(many=True),
                   operation_id="round_list")
    def get(self, request):
        asked = given(serializers.RoundsQuery, request.query_params)
        found = service.rounds_for(request.user, asked["mine"], asked["state"])
        return Response(serializers.RoundLine(found, many=True).data)


class Join(MatchView):
    permission_classes = [auth.Approved]

    @extend_schema(tags=TAGS, request=None, responses=serializers.Joined, operation_id="round_join")
    def post(self, request, round_id: int, side: str):
        seat = service.join(service.round_of(round_id), side, request.user)
        return Response(serializers.Joined(seat).data)


class Start(MatchView):
    permission_classes = [auth.IsOperator]

    @extend_schema(tags=TAGS, request=None, responses=serializers.PhaseShown, operation_id="round_start")
    def post(self, request, round_id: int):
        return Response(serializers.PhaseShown(service.start_round(service.round_of(round_id))).data)


class End(MatchView):
    permission_classes = [auth.IsOperator]

    @extend_schema(tags=TAGS, request=None, responses=serializers.Ended, operation_id="round_end")
    def post(self, request, round_id: int):
        return Response(serializers.Ended(service.end_round(service.round_of(round_id), "ended_by_operator")).data)


class RoundDetail(MatchView):
    permission_classes = [auth.InRound]

    @extend_schema(tags=TAGS, responses=serializers.RoundShown, operation_id="round_read")
    def get(self, request, round_id: int):
        return Response(serializers.RoundShown(request.round).data)


class Score(MatchView):
    permission_classes = [auth.InRound]

    @extend_schema(tags=TAGS, parameters=[serializers.ScoreQuery], responses=serializers.Score,
                   operation_id="round_score")
    def get(self, request, round_id: int):
        asked = given(serializers.ScoreQuery, request.query_params)
        found = service.score_for(request.round, bool(request.user.is_staff), request.operator,
                                  asked.get("correlation"))
        return Response(serializers.Score(found.shown()).data)


class Topology(MatchView):
    permission_classes = [auth.InRound]

    @extend_schema(tags=TAGS, responses=serializers.Topology, operation_id="round_topology")
    def get(self, request, round_id: int):
        side = service.shown_side(request.seats, request.operator)
        return Response(serializers.Topology(service.map_of(request.round, side)).data)


class SiteRequests(MatchView):
    permission_classes = [auth.InRound]

    @extend_schema(tags=TAGS, parameters=[serializers.SiteQuery], responses=serializers.SiteRequest(many=True),
                   operation_id="round_site_requests")
    def get(self, request, round_id: int):
        after = given(serializers.SiteQuery, request.query_params)["after"]
        return Response(serializers.SiteRequest(service.site_requests(request.round, request.seats, after),
                                                many=True).data)


class TerminalAuth(MatchView):
    def get_permissions(self):
        return [auth.HasSeat(self.kwargs["side"])()]

    @extend_schema(tags=TAGS, responses={204: None}, operation_id="round_terminal_auth")
    def get(self, request, round_id: int, side: str):
        service.terminal_open(request.round)
        return Response(status=status.HTTP_204_NO_CONTENT)


class Forfeit(MatchView):
    side = ""

    def get_permissions(self):
        return [auth.HasSeat(self.side)()]

    def post(self, request, round_id: int):
        return Response(serializers.Ended(service.forfeit(request.round, request.seat)).data)


class AttackForfeit(Forfeit):
    side = "attack"

    @extend_schema(tags=["attack"], request=None, responses=serializers.Ended, operation_id="attack_forfeit")
    def post(self, request, round_id: int):
        return super().post(request, round_id)


class DefenceForfeit(Forfeit):
    side = "defence"

    @extend_schema(tags=["defence"], request=None, responses=serializers.Ended, operation_id="defence_forfeit")
    def post(self, request, round_id: int):
        return super().post(request, round_id)


class StaffRange(MatchView):
    permission_classes = [accounts.IsStaff]

    @extend_schema(tags=STAFF_TAGS, responses=serializers.Range, operation_id="staff_range")
    def get(self, request):
        return Response(serializers.Range({"slots": [asdict(one) for one in service.slots()]}).data)


class RecordProbes(MatchView):
    permission_classes = [accounts.IsStaff]

    @extend_schema(tags=STAFF_TAGS, request=None, responses={202: serializers.ProbeLease},
                   operation_id="staff_probes_record")
    def post(self, request, wargame_id: str):
        held = service.record_probes(wargame_id, request.user)
        return Response(serializers.ProbeLease(held).data, status=status.HTTP_202_ACCEPTED)


class ProbeProgress(MatchView):
    permission_classes = [accounts.IsStaff]

    @extend_schema(tags=STAFF_TAGS, responses=serializers.ProbeProgress, operation_id="staff_probes_progress")
    def get(self, request, lease_id: int):
        return Response(serializers.ProbeProgress(asdict(service.probe_progress(lease_id))).data)


class Passthrough(renderers.BaseRenderer):
    media_type = "*/*"
    format = "site"
    charset = "utf-8"

    def render(self, data, accepted_media_type=None, renderer_context=None):
        if isinstance(data, str):
            return data.encode("utf-8")
        return json.dumps(data).encode("utf-8")


@extend_schema(exclude=True)
class SiteProxy(APIView):
    authentication_classes = (auth.SeatTokenAuthentication, auth.FramedSessionAuthentication)
    permission_classes = [auth.InRound]
    renderer_classes = [Passthrough]

    def answer(self, request, round_id: int, host: str, rest: str = ""):
        path = "/" + rest + (f"?{request.META['QUERY_STRING']}" if request.META.get("QUERY_STRING") else "")
        body = request.body.decode("utf-8", "replace") if request.body else None
        fetched = service.browse(request.round, request.seats, request.method, host, path, dict(request.headers),
                                 body)
        kind = next((value for name, value in fetched.headers if name.lower() == "content-type"), "text/plain")
        answered = Response(fetched.body, status=fetched.status, content_type=kind)
        for name, value in fetched.headers:
            if name.lower() == "content-type":
                continue
            answered[name] = value
        if fetched.hp_left is not None:
            answered["X-Origin-HP"] = str(fetched.hp_left)
        return answered

    get = post = put = patch = delete = options = answer

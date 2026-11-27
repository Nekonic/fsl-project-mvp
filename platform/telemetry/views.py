from drf_spectacular.utils import extend_schema
from rest_framework.response import Response

from telemetry import access as access_log
from telemetry import alerts as alert_feed
from telemetry import events as log
from telemetry import serializers
from training.round import access as auth
from training.round.views_catch_up import ALERTS_READ, CatchingUpView


class RoundEvents(CatchingUpView):
    authentication_classes = auth.ROUND_AUTHENTICATION
    permission_classes = [auth.InRound]

    @extend_schema(tags=["match"], parameters=[serializers.Cursor], responses=serializers.Page,
                   operation_id="round_events")
    def get(self, request, round_id: int):
        given = serializers.Cursor(data=request.query_params)
        given.is_valid(raise_exception=True)
        viewer = log.Viewer(sides=frozenset(player.side for player in request.players),
                            staff=bool(getattr(request.user, "is_staff", False)), operator=request.operator)
        page = log.after(request.round.pk, given.validated_data["after"], viewer, kinds=given.validated_data.get("kinds"))
        return Response(serializers.Page(page).data)


def given(serializer, data):
    checked = serializer(data=data)
    checked.is_valid(raise_exception=True)
    return checked.validated_data


class DefenceView(CatchingUpView):
    authentication_classes = auth.ROUND_AUTHENTICATION
    permission_classes = [auth.IsPlayer("defence")]


class Alerts(DefenceView):
    needs_reads = (ALERTS_READ,)

    @extend_schema(tags=["defence"], parameters=[serializers.AlertQuery], responses=serializers.Alerts,
                   operation_id="defence_alerts")
    def get(self, request, round_id: int):
        asked = given(serializers.AlertQuery, request.query_params)
        rows, next_id = alert_feed.alerts(request.round, asked["after"], asked.get("engine", ""),
                                          asked.get("rule", ""), asked.get("src", ""))
        return Response(serializers.Alerts({"alerts": rows, "next": next_id}).data)


class Traffic(DefenceView):
    @extend_schema(tags=["defence"], parameters=[serializers.TrafficQuery], responses=serializers.Traffic,
                   operation_id="defence_traffic")
    def get(self, request, round_id: int):
        asked = given(serializers.TrafficQuery, request.query_params)
        return Response(serializers.Traffic(access_log.traffic(request.round, asked["after"])).data)

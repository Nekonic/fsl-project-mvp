from drf_spectacular.utils import extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from telemetry import access as access_log
from telemetry import alerts as alert_feed
from telemetry import events as log
from telemetry import serializers
from training.round import access as auth


class RoundEvents(APIView):
    authentication_classes = auth.ROUND_AUTHENTICATION
    permission_classes = [auth.InRound]

    @extend_schema(tags=["match"], parameters=[serializers.Cursor], responses=serializers.Page,
                   operation_id="round_events")
    def get(self, request, round_id: int):
        given = serializers.Cursor(data=request.query_params)
        given.is_valid(raise_exception=True)
        viewer = log.Viewer(sides=frozenset(seat.side for seat in request.seats),
                            staff=bool(getattr(request.user, "is_staff", False)), operator=request.operator)
        page = log.after(request.round.pk, given.validated_data["after"], viewer)
        return Response(serializers.Page(page).data)


def given(serializer, data):
    checked = serializer(data=data)
    checked.is_valid(raise_exception=True)
    return checked.validated_data


class DefenceView(APIView):
    authentication_classes = auth.ROUND_AUTHENTICATION
    permission_classes = [auth.HasSeat("defence")]


class Alerts(DefenceView):
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

from drf_spectacular.utils import extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from events import log, serializers
from match import auth


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

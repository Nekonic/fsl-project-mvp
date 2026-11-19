from drf_spectacular.utils import extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts import service as accounts
from events import log, serializers


class RoundEvents(APIView):
    permission_classes = [accounts.IsStaff]

    @extend_schema(tags=["match"], parameters=[serializers.Cursor], responses=serializers.Page,
                   operation_id="round_events")
    def get(self, request, round_id: int):
        given = serializers.Cursor(data=request.query_params)
        given.is_valid(raise_exception=True)
        page = log.after(round_id, given.validated_data["after"], log.Viewer(staff=True))
        return Response(serializers.Page(page).data)

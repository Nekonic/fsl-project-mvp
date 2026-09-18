from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from api.models import Session
from api.serializers import CaseSerializer, SessionSerializer


@api_view(["POST"])
def create_session(request):
    serializer = SessionSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    session = serializer.save()
    return Response(SessionSerializer(session).data, status=status.HTTP_201_CREATED)


@api_view(["GET"])
def session_detail(request, session_id):
    session = get_object_or_404(Session, pk=session_id)
    return Response(SessionSerializer(session).data)


@api_view(["POST"])
def close_session(request, session_id):
    session = get_object_or_404(Session, pk=session_id)
    session.ended_at = timezone.now()
    session.save(update_fields=["ended_at"])
    return Response(SessionSerializer(session).data)


@api_view(["GET", "POST"])
def session_cases(request, session_id):
    session = get_object_or_404(Session, pk=session_id)

    if request.method == "GET":
        return Response(CaseSerializer(session.cases.all(), many=True).data)

    serializer = CaseSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    case = serializer.save(session=session)
    return Response(CaseSerializer(case).data, status=status.HTTP_201_CREATED)

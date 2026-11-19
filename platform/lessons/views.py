from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts import service as accounts
from lessons import serializers, service
from match import auth

TAGS = ["lessons"]
STAFF_TAGS = ["staff"]


def given(serializer, data):
    checked = serializer(data=data)
    checked.is_valid(raise_exception=True)
    return checked.validated_data


class LessonView(APIView):
    permission_classes = [auth.Approved]


class Lessons(LessonView):
    @extend_schema(tags=TAGS, request=serializers.OpenLesson, responses={201: serializers.LessonOpened},
                   operation_id="lesson_open")
    def post(self, request):
        opened = service.open_lesson(request.user, given(serializers.OpenLesson, request.data)["problem"])
        return Response(serializers.LessonOpened(opened).data, status=status.HTTP_201_CREATED)

    @extend_schema(tags=TAGS, parameters=[serializers.LessonsQuery], responses=serializers.LessonLine(many=True),
                   operation_id="lesson_list")
    def get(self, request):
        given(serializers.LessonsQuery, request.query_params)
        return Response(serializers.LessonLine(service.lessons_for(request.user), many=True).data)


class OneLesson(LessonView):
    @extend_schema(tags=TAGS, responses=serializers.LessonShown, operation_id="lesson_read")
    def get(self, request, round_id: int):
        return Response(serializers.LessonShown(service.lesson(round_id, request.user)).data)


class CheckStep(LessonView):
    @extend_schema(tags=TAGS, request=serializers.CheckAsk, responses=serializers.Checked,
                   operation_id="lesson_step_check")
    def post(self, request, round_id: int, order: int):
        answer = given(serializers.CheckAsk, request.data)["answer"]
        return Response(serializers.Checked(service.check(round_id, request.user, order, answer)).data)


class StepHint(LessonView):
    @extend_schema(tags=TAGS, request=serializers.HintAsk, responses=serializers.Hint,
                   operation_id="lesson_step_hint")
    def post(self, request, round_id: int, order: int):
        n = given(serializers.HintAsk, request.data)["n"]
        return Response(serializers.Hint(service.hint(round_id, request.user, order, n)).data)


class EndLesson(LessonView):
    @extend_schema(tags=TAGS, request=None, responses=serializers.Ended, operation_id="lesson_end")
    def post(self, request, round_id: int):
        return Response(serializers.Ended(service.end(round_id, request.user)).data)


class TryStep(APIView):
    permission_classes = [accounts.IsStaff]

    @extend_schema(tags=STAFF_TAGS, request=serializers.TryAsk, responses=serializers.Checked,
                   operation_id="staff_step_try")
    def post(self, request, problem_id: int, order: int):
        asked = given(serializers.TryAsk, request.data)
        return Response(serializers.Checked(service.try_step(problem_id, order, asked["round"], asked["answer"])).data)

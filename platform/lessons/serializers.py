from rest_framework import serializers

from lessons.models import VERDICTS
from lessons.service import PHASES

LESSON_PHASES = [(phase, phase) for phase in PHASES]


class OpenLesson(serializers.Serializer):
    problem = serializers.IntegerField()


class LessonsQuery(serializers.Serializer):
    mine = serializers.BooleanField(required=False, default=True)


class LessonLine(serializers.Serializer):
    round = serializers.IntegerField()
    problem = serializers.IntegerField()
    phase = serializers.ChoiceField(choices=LESSON_PHASES)
    passed_order = serializers.IntegerField()


class StepLine(serializers.Serializer):
    order = serializers.IntegerField()
    body = serializers.CharField()
    opens = serializers.CharField()
    hints_available = serializers.IntegerField()


class Brief(serializers.Serializer):
    id = serializers.IntegerField()
    side = serializers.CharField()
    title = serializers.CharField()
    summary = serializers.CharField()
    body = serializers.CharField()


class Standing(serializers.Serializer):
    passed_order = serializers.IntegerField()
    passed_at = serializers.DateTimeField(allow_null=True)


class LessonOpened(serializers.Serializer):
    round = serializers.IntegerField()
    lease = serializers.IntegerField()
    phase = serializers.ChoiceField(choices=LESSON_PHASES)


class LessonShown(LessonOpened):
    problem = Brief()
    steps = StepLine(many=True)
    current = serializers.IntegerField(allow_null=True)
    progress = Standing()


class CheckAsk(serializers.Serializer):
    answer = serializers.JSONField(required=False, allow_null=True, default=None)


class TryAsk(CheckAsk):
    round = serializers.IntegerField()


class Checked(serializers.Serializer):
    verdict = serializers.ChoiceField(choices=VERDICTS)
    detail_code = serializers.CharField(allow_null=True)
    next = serializers.IntegerField(allow_null=True)


class HintAsk(serializers.Serializer):
    n = serializers.IntegerField()


class Hint(serializers.Serializer):
    hint = serializers.CharField()
    n = serializers.IntegerField()
    left = serializers.IntegerField()


class Ended(serializers.Serializer):
    ended = serializers.DateTimeField()

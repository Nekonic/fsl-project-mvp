from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from training.models import PROBLEM_KINDS, PROBLEM_SIDES

MATCHUPS = ["pvp", "def_vs_bot", "atk_vs_bot"]


class RoundSetup(serializers.Serializer):
    matchups = serializers.ListField(child=serializers.ChoiceField(choices=MATCHUPS))
    posture = serializers.CharField(allow_null=True, required=False)
    probe_cases = serializers.ListField(child=serializers.CharField(), default=list)
    objectives = serializers.ListField(child=serializers.CharField(), default=list)
    traffic = serializers.CharField(allow_null=True, required=False)
    benign_every_s = serializers.IntegerField(required=False)
    time_limit_s = serializers.IntegerField(allow_null=True, required=False)
    bot_steps = serializers.ListField(child=serializers.CharField(), required=False)
    cards = serializers.ListField(child=serializers.CharField(), required=False)


class InlinePosture(serializers.Serializer):
    name = serializers.CharField()
    suricata_rules = serializers.CharField(allow_blank=True, default="")
    waf_files = serializers.DictField(child=serializers.CharField(allow_blank=True, trim_whitespace=False))


class ProblemFields(serializers.Serializer):
    kind = serializers.ChoiceField(choices=PROBLEM_KINDS)
    wargame = serializers.CharField()
    side = serializers.ChoiceField(choices=PROBLEM_SIDES)
    title = serializers.CharField()
    summary = serializers.CharField(allow_blank=True, default="")
    body = serializers.CharField(allow_blank=True, default="")
    published = serializers.BooleanField(default=False)


class StoredProblemFields(ProblemFields):
    id = serializers.IntegerField()
    revision = serializers.IntegerField()
    author = serializers.CharField(allow_null=True)
    updated = serializers.DateTimeField()


class Document(serializers.Serializer):
    problem = ProblemFields()
    round = RoundSetup(allow_null=True, required=False)
    start_posture = InlinePosture(allow_null=True, required=False)


class StoredDocument(Document):
    problem = StoredProblemFields()


class RevisedDocument(Document):
    base_revision = serializers.IntegerField()


class Validation(serializers.Serializer):
    ok = serializers.BooleanField()
    errors = serializers.ListField(child=serializers.DictField())


class StaffProblem(serializers.Serializer):
    id = serializers.IntegerField()
    kind = serializers.CharField()
    wargame = serializers.CharField(source="wargame_id")
    side = serializers.CharField()
    title = serializers.CharField()
    published = serializers.BooleanField()
    revision = serializers.IntegerField()
    updated = serializers.DateTimeField()


class Posture(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    wargame = serializers.CharField(source="wargame_id")
    name = serializers.CharField()
    suricata_rules = serializers.CharField(allow_blank=True, default="")
    waf_files = serializers.DictField(child=serializers.CharField(allow_blank=True, trim_whitespace=False))


class Wargame(serializers.Serializer):
    id = serializers.CharField()
    title = serializers.CharField()
    image = serializers.CharField()
    public_url = serializers.CharField()
    hosts = serializers.ListField(child=serializers.CharField())
    objective_model = serializers.CharField()
    case_file = serializers.CharField()
    default_traffic = serializers.CharField(allow_null=True)
    waf_files = serializers.SerializerMethodField()

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_waf_files(self, wargame) -> list[str]:
        return list(self.context.get("waf_files", ()))


class LearnerProblemSummary(serializers.Serializer):
    id = serializers.IntegerField()
    kind = serializers.CharField()
    wargame = serializers.CharField(source="wargame_id")
    side = serializers.CharField()
    title = serializers.CharField()
    summary = serializers.CharField()


class LearnerProblem(LearnerProblemSummary):
    body = serializers.CharField()

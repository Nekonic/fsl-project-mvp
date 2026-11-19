from rest_framework import serializers

from content.models import KINDS, PANES, SIDES

MATCHUPS = ["pvp", "def_vs_bot", "atk_vs_bot"]


class Check(serializers.Serializer):
    kind = serializers.CharField()
    params = serializers.DictField()


class StaffStep(serializers.Serializer):
    order = serializers.IntegerField()
    body = serializers.CharField()
    opens = serializers.ChoiceField(choices=PANES, default="none")
    check = Check()
    answer = serializers.JSONField(allow_null=True, required=False)
    hints = serializers.ListField(child=serializers.CharField(), default=list)


class HpRule(serializers.Serializer):
    budget = serializers.IntegerField()
    per_request = serializers.IntegerField()
    refused_x = serializers.IntegerField()
    burst_per_s = serializers.IntegerField()
    burst_x = serializers.IntegerField()


class RoundSetup(serializers.Serializer):
    matchups = serializers.ListField(child=serializers.ChoiceField(choices=MATCHUPS))
    posture = serializers.CharField(allow_null=True, required=False)
    probe_cases = serializers.ListField(child=serializers.CharField(), default=list)
    objectives = serializers.ListField(child=serializers.CharField(), default=list)
    hp = HpRule()
    traffic = serializers.CharField(allow_null=True, required=False)
    benign_every_s = serializers.IntegerField(required=False)
    time_limit_s = serializers.IntegerField(allow_null=True, required=False)


class InlinePosture(serializers.Serializer):
    name = serializers.CharField()
    suricata_rules = serializers.CharField(allow_blank=True, default="")
    crs_tuning = serializers.DictField()


class ProblemFields(serializers.Serializer):
    kind = serializers.ChoiceField(choices=KINDS)
    wargame = serializers.CharField()
    side = serializers.ChoiceField(choices=SIDES)
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
    steps = StaffStep(many=True, default=list)
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
    crs_tuning = serializers.DictField()


class Wargame(serializers.Serializer):
    id = serializers.CharField()
    title = serializers.CharField()
    image = serializers.CharField()
    public_url = serializers.CharField()
    hosts = serializers.ListField(child=serializers.CharField())
    objective_model = serializers.CharField()
    case_file = serializers.CharField()
    default_traffic = serializers.CharField(allow_null=True)


class LearnerStep(serializers.Serializer):
    order = serializers.IntegerField()
    body = serializers.CharField()
    opens = serializers.CharField()
    kind = serializers.SerializerMethodField()
    options = serializers.SerializerMethodField()
    hints_available = serializers.SerializerMethodField()

    def get_kind(self, step) -> str:
        return step.check_spec.get("kind", "")

    def get_options(self, step) -> list[str]:
        return list(step.check_spec.get("params", {}).get("options", [])) if self.get_kind(step) == "choice" else []

    def get_hints_available(self, step) -> int:
        return len(step.hints)


class LearnerProblemSummary(serializers.Serializer):
    id = serializers.IntegerField()
    kind = serializers.CharField()
    wargame = serializers.CharField(source="wargame_id")
    side = serializers.CharField()
    title = serializers.CharField()
    summary = serializers.CharField()


class LearnerProblem(LearnerProblemSummary):
    body = serializers.CharField()
    steps = LearnerStep(many=True)

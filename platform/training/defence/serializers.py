from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

VERDICTS = [(verdict, verdict) for verdict in ("tp", "fn", "fp", "tn")]
UNTESTED = [(reason, reason) for reason in ("tool_case", "not_recorded")]


class Text(serializers.Serializer):
    text = serializers.CharField(allow_blank=True, trim_whitespace=False, max_length=200000)


class IdsTest(Text):
    cases = serializers.ListField(child=serializers.CharField(max_length=100), required=False, max_length=200)


class WafFilesGiven(serializers.Serializer):
    files = serializers.DictField(child=serializers.CharField(allow_blank=True, trim_whitespace=False,
                                                              max_length=200000))


class WafTest(WafFilesGiven):
    cases = serializers.ListField(child=serializers.CharField(max_length=100), required=False, max_length=200)


class WafApply(WafFilesGiven):
    base_version = serializers.IntegerField(min_value=0)
    tested = serializers.IntegerField(min_value=1, required=False, allow_null=True)


class DefenceBrief(serializers.Serializer):
    title = serializers.CharField()
    summary = serializers.CharField()
    body = serializers.CharField()


class DefenceTarget(serializers.Serializer):
    public_url = serializers.CharField()
    hosts = serializers.ListField(child=serializers.CharField())


class ObjectiveState(serializers.Serializer):
    key = serializers.CharField()
    name = serializers.CharField()
    state = serializers.ChoiceField(choices=[("kept", "kept"), ("lost", "lost")])
    seen = serializers.BooleanField()


class Version(serializers.Serializer):
    version = serializers.IntegerField()


class DefenceState(serializers.Serializer):
    round = serializers.IntegerField()
    matchup = serializers.CharField()
    phase = serializers.CharField()
    started = serializers.DateTimeField(allow_null=True)
    ends_at = serializers.DateTimeField(allow_null=True)
    end_reason = serializers.CharField()
    brief = DefenceBrief()
    target = DefenceTarget()
    objectives = ObjectiveState(many=True)
    ids = Version()
    waf = Version()
    alerts_total = serializers.IntegerField()


class ProbeCase(serializers.Serializer):
    case = serializers.CharField()
    malicious = serializers.BooleanField()
    recorded = serializers.BooleanField()
    tool_case = serializers.BooleanField()


class IdsRules(serializers.Serializer):
    text = serializers.CharField(trim_whitespace=False)
    version = serializers.IntegerField()
    recorded = serializers.BooleanField()


class AppliedVersion(serializers.Serializer):
    version = serializers.IntegerField()
    applied_at = serializers.DateTimeField()
    tested = serializers.IntegerField(source="tested_id", allow_null=True)
    same_as_tested = serializers.BooleanField()
    sha = serializers.CharField()
    source = serializers.ChoiceField(choices=[(source, source) for source in ("setup", "console", "terminal")])


class WafFile(serializers.Serializer):
    path = serializers.CharField()
    text = serializers.CharField(trim_whitespace=False, allow_blank=True)


class VersionFiles(AppliedVersion):
    files = serializers.SerializerMethodField()

    @extend_schema_field(WafFile(many=True))
    def get_files(self, made) -> list[dict]:
        return WafFile([{"path": path, "text": text} for path, text in made.files.items()], many=True).data


class RuleError(serializers.Serializer):
    path = serializers.CharField()
    code = serializers.CharField()
    line = serializers.IntegerField(allow_null=True)
    message = serializers.CharField()


class RuleCheck(serializers.Serializer):
    ok = serializers.BooleanField()
    errors = RuleError(many=True)


class ProbeAlert(serializers.Serializer):
    rule = serializers.CharField()
    signature = serializers.CharField()


class CaseVerdict(serializers.Serializer):
    case = serializers.CharField()
    malicious = serializers.BooleanField()
    verdict = serializers.ChoiceField(choices=VERDICTS)
    corroborated = serializers.BooleanField(allow_null=True)
    alerts = ProbeAlert(many=True)
    recorded_run = serializers.BooleanField()


class VerdictTotals(serializers.Serializer):
    tp = serializers.IntegerField()
    fn = serializers.IntegerField()
    fp = serializers.IntegerField()
    tn = serializers.IntegerField()


class UntestedCase(serializers.Serializer):
    case = serializers.CharField()
    reason = serializers.ChoiceField(choices=UNTESTED)


class Change(serializers.Serializer):
    case = serializers.CharField()
    was = serializers.ChoiceField(choices=VERDICTS)
    now = serializers.ChoiceField(choices=VERDICTS)


class RuleTestResult(serializers.Serializer):
    test = serializers.IntegerField()
    ok = serializers.BooleanField()
    passed = serializers.BooleanField()
    failed_benign = serializers.ListField(child=serializers.CharField())
    untested_benign = serializers.ListField(child=serializers.CharField())
    errors = RuleError(many=True)
    cases = CaseVerdict(many=True)
    totals = VerdictTotals()
    untested = UntestedCase(many=True)
    against_applied = Change(many=True)


class WafApplied(serializers.Serializer):
    version = serializers.IntegerField()
    applied_at = serializers.DateTimeField()
    same_as_tested = serializers.BooleanField()
    sha = serializers.CharField()


class WafRead(serializers.Serializer):
    files = WafFile(many=True)
    sha = serializers.CharField()
    version = serializers.IntegerField()
    recorded = serializers.BooleanField()


class AnalystSsh(serializers.Serializer):
    host = serializers.CharField()
    port = serializers.IntegerField()
    user = serializers.CharField()
    private_key = serializers.CharField()
    expires_at = serializers.DateTimeField(allow_null=True)
    target_host = serializers.CharField()
    target_user = serializers.CharField()


class DefenceTerminal(serializers.Serializer):
    ws_url = serializers.CharField()
    ssh = AnalystSsh()


class KibanaSpace(serializers.Serializer):
    space_url = serializers.CharField()

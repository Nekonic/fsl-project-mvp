from rest_framework import serializers

VERDICTS = [(verdict, verdict) for verdict in ("tp", "fn", "fp", "tn")]
UNTESTED = [(reason, reason) for reason in ("tool_case", "not_recorded")]
DISABLE_LONGEST_MINUTES = 24 * 60
DISABLE_MINUTES = 60


class Text(serializers.Serializer):
    text = serializers.CharField(allow_blank=True, trim_whitespace=False, max_length=200000)


class IdsTest(Text):
    cases = serializers.ListField(child=serializers.CharField(max_length=100), required=False, max_length=200)


class IdsApply(Text):
    base_version = serializers.IntegerField(min_value=0)
    tested = serializers.IntegerField(min_value=1, required=False, allow_null=True)


class Exclusion(serializers.Serializer):
    rule_id = serializers.IntegerField(required=False)
    tag = serializers.CharField(required=False, max_length=64)
    target = serializers.CharField(required=False, allow_blank=True, max_length=200)
    path = serializers.CharField(required=False, allow_blank=True, max_length=200)


class Thresholds(serializers.Serializer):
    inbound = serializers.IntegerField(required=False)
    outbound = serializers.IntegerField(required=False)


class WafPosture(serializers.Serializer):
    paranoia = serializers.IntegerField()
    exclusions = Exclusion(many=True, required=False)
    thresholds = Thresholds(required=False)
    detection_only = serializers.BooleanField(required=False)


class WafCheck(serializers.Serializer):
    posture = WafPosture()


class WafTest(WafCheck):
    cases = serializers.ListField(child=serializers.CharField(max_length=100), required=False, max_length=200)


class WafApply(WafCheck):
    base_version = serializers.IntegerField(min_value=0)
    tested = serializers.IntegerField(min_value=1, required=False, allow_null=True)


class Disable(serializers.Serializer):
    sid = serializers.IntegerField(min_value=1)
    minutes = serializers.FloatField(min_value=0.1, max_value=DISABLE_LONGEST_MINUTES, default=DISABLE_MINUTES)
    reason = serializers.CharField(required=False, allow_blank=True, default="", max_length=500)


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


class AppliedVersion(serializers.Serializer):
    version = serializers.IntegerField()
    applied_at = serializers.DateTimeField()
    tested = serializers.IntegerField(source="tested_id", allow_null=True)
    same_as_tested = serializers.BooleanField()


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
    errors = RuleError(many=True)
    cases = CaseVerdict(many=True)
    totals = VerdictTotals()
    untested = UntestedCase(many=True)
    against_applied = Change(many=True)


class SensorApplied(serializers.Serializer):
    name = serializers.CharField()
    ok = serializers.BooleanField()


class IdsApplied(serializers.Serializer):
    version = serializers.IntegerField()
    applied_at = serializers.DateTimeField()
    same_as_tested = serializers.BooleanField()
    sensors = SensorApplied(many=True)


class WafApplied(serializers.Serializer):
    version = serializers.IntegerField()
    applied_at = serializers.DateTimeField()
    same_as_tested = serializers.BooleanField()


class WafRead(serializers.Serializer):
    posture = WafPosture()
    version = serializers.IntegerField()


class DisabledRule(serializers.Serializer):
    sid = serializers.IntegerField()
    original = serializers.CharField()
    reason = serializers.CharField()
    expires_at = serializers.DateTimeField()


class DisabledNow(serializers.Serializer):
    sid = serializers.IntegerField()
    expires_at = serializers.DateTimeField()


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

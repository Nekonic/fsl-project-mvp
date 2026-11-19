from rest_framework import serializers

from attack import service

METHODS = [(method, method) for method in service.REQUEST_METHODS]


class AttackOrigin(serializers.Serializer):
    id = serializers.CharField()
    label = serializers.CharField()
    ip = serializers.CharField()


class Rule(serializers.Serializer):
    budget = serializers.IntegerField()
    per_request = serializers.IntegerField()
    refused_x = serializers.IntegerField()
    burst_per_s = serializers.IntegerField()
    burst_x = serializers.IntegerField()
    refused_statuses = serializers.ListField(child=serializers.IntegerField())


class HpBlock(serializers.Serializer):
    origin = AttackOrigin(allow_null=True)
    left = serializers.IntegerField()
    budget = serializers.IntegerField()
    origins_left = serializers.IntegerField()
    spent = serializers.ListField(child=serializers.CharField())
    rule = Rule()


class OriginLine(serializers.Serializer):
    id = serializers.CharField()
    label = serializers.CharField()
    ip = serializers.CharField()
    left = serializers.IntegerField()
    budget = serializers.IntegerField()
    spent_at = serializers.DateTimeField(allow_null=True)


class AttackBrief(serializers.Serializer):
    title = serializers.CharField()
    summary = serializers.CharField()
    body = serializers.CharField()


class AttackTarget(serializers.Serializer):
    public_url = serializers.CharField()
    hosts = serializers.ListField(child=serializers.CharField())


class ObjectiveLine(serializers.Serializer):
    key = serializers.CharField()
    name = serializers.CharField()
    state = serializers.ChoiceField(choices=["kept", "lost"])


class AttackState(serializers.Serializer):
    round = serializers.IntegerField()
    matchup = serializers.CharField()
    phase = serializers.CharField()
    started = serializers.DateTimeField(allow_null=True)
    ends_at = serializers.DateTimeField(allow_null=True)
    end_reason = serializers.CharField()
    brief = AttackBrief()
    target = AttackTarget()
    objectives = ObjectiveLine(many=True)
    origins = OriginLine(many=True)
    hp = HpBlock()


class CaseEntry(serializers.Serializer):
    case = serializers.CharField()
    kind = serializers.ChoiceField(choices=["http", "tool"])
    malicious = serializers.BooleanField()
    title = serializers.CharField()


class SendRequest(serializers.Serializer):
    method = serializers.ChoiceField(choices=METHODS)
    path = serializers.CharField(max_length=8192, trim_whitespace=False)
    host = serializers.CharField(required=False, allow_null=True, default=None)
    query = serializers.DictField(child=serializers.CharField(allow_blank=True, trim_whitespace=False),
                                  required=False, default=dict)
    headers = serializers.DictField(child=serializers.CharField(allow_blank=True, trim_whitespace=False,
                                                                max_length=8192),
                                    required=False, default=dict)
    body = serializers.CharField(required=False, allow_null=True, allow_blank=True, trim_whitespace=False,
                                 default=None, max_length=1048576)


class Sent(serializers.Serializer):
    action = serializers.IntegerField()
    marker = serializers.CharField()
    status = serializers.IntegerField()
    headers = serializers.ListField(child=serializers.ListField(child=serializers.CharField()))
    body = serializers.CharField()
    truncated = serializers.BooleanField()
    hp = HpBlock()


class FireCase(serializers.Serializer):
    case = serializers.CharField(max_length=100)


class Fired(serializers.Serializer):
    action = serializers.IntegerField()
    marker = serializers.CharField()
    run = serializers.IntegerField(allow_null=True)
    status = serializers.IntegerField(allow_null=True)
    hp = HpBlock()


class ToolSpec(serializers.Serializer):
    tool = serializers.CharField()
    args_schema = serializers.DictField()


class RunLine(serializers.Serializer):
    run = serializers.IntegerField()
    tool = serializers.CharField()
    started = serializers.DateTimeField()
    ended = serializers.DateTimeField(allow_null=True)
    exit_code = serializers.IntegerField(allow_null=True)
    stopped_by = serializers.CharField(allow_null=True)


class Tools(serializers.Serializer):
    tools = ToolSpec(many=True)
    runs = RunLine(many=True)
    hp = HpBlock()


class StartTool(serializers.Serializer):
    tool = serializers.CharField(max_length=32)
    args = serializers.ListField(child=serializers.CharField(allow_blank=True, trim_whitespace=False,
                                                             max_length=service.LONGEST_ARG),
                                 max_length=service.MOST_ARGS, default=list)


class Started(serializers.Serializer):
    run = serializers.IntegerField()
    action = serializers.IntegerField()
    hp = HpBlock()


class OutputAfter(serializers.Serializer):
    after = serializers.IntegerField(min_value=0, default=0)


class RunPage(serializers.Serializer):
    output = serializers.CharField(allow_blank=True)
    offset = serializers.IntegerField()
    done = serializers.BooleanField()
    exit_code = serializers.IntegerField(allow_null=True)
    stopped_by = serializers.CharField(allow_null=True)
    hp = HpBlock()


class Loot(serializers.Serializer):
    value = serializers.JSONField()


class LootedObjective(serializers.Serializer):
    key = serializers.CharField()
    name = serializers.CharField()


class Looted(serializers.Serializer):
    lost = serializers.BooleanField()
    objective = LootedObjective(allow_null=True)
    hp = HpBlock()


class NextOrigin(serializers.Serializer):
    origin = AttackOrigin(allow_null=True)
    hp = HpBlock()


class Ssh(serializers.Serializer):
    host = serializers.CharField()
    port = serializers.IntegerField()
    user = serializers.CharField()
    private_key = serializers.CharField()
    expires_at = serializers.DateTimeField(allow_null=True)
    target_host = serializers.CharField()
    target_user = serializers.CharField()


class AttackTerminal(serializers.Serializer):
    ws_url = serializers.CharField()
    ssh = Ssh()
    hp = HpBlock()

from drf_spectacular.utils import extend_schema
from rest_framework.response import Response

from training.defence import kibana_gate, serializers
from training.defence import rules as service
from training.defence import terminal as defence_terminal
from training.round import access as auth
from training.round.views_catch_up import CatchingUpView

TAGS = ["defence"]
IDS, WAF = "ids", "waf"


def given(serializer, data):
    checked = serializer(data=data)
    checked.is_valid(raise_exception=True)
    return checked.validated_data


def test_result(found, made) -> dict:
    return serializers.RuleTestResult({"test": made.pk, "passed": False, "failed_benign": [], "untested_benign": [],
                                       **service.titled_result(found, made.result)}).data


class DefenceView(CatchingUpView):
    authentication_classes = auth.ROUND_AUTHENTICATION
    permission_classes = [auth.IsPlayer("defence")]


class State(DefenceView):
    @extend_schema(tags=TAGS, responses=serializers.DefenceState, operation_id="defence_state")
    def get(self, request, round_id: int):
        return Response(serializers.DefenceState(service.state(request.round)).data)


class Probes(DefenceView):
    @extend_schema(tags=TAGS, responses=serializers.ProbeCase(many=True), operation_id="defence_probes")
    def get(self, request, round_id: int):
        return Response(serializers.ProbeCase(service.probes(request.round), many=True).data)


class IdsRules(DefenceView):
    @extend_schema(tags=TAGS, responses=serializers.IdsRules, operation_id="defence_ids_rules")
    def get(self, request, round_id: int):
        return Response(serializers.IdsRules(service.ids_rules(request.round)).data)


class IdsVersions(DefenceView):
    @extend_schema(tags=TAGS, responses=serializers.AppliedVersion(many=True), operation_id="defence_ids_versions")
    def get(self, request, round_id: int):
        return Response(serializers.AppliedVersion(service.versions(request.round, IDS), many=True).data)


class WafVersions(DefenceView):
    @extend_schema(tags=TAGS, responses=serializers.AppliedVersion(many=True), operation_id="defence_waf_versions")
    def get(self, request, round_id: int):
        return Response(serializers.AppliedVersion(service.versions(request.round, WAF), many=True).data)


class IdsVersion(DefenceView):
    @extend_schema(tags=TAGS, responses=serializers.VersionFiles, operation_id="defence_ids_version")
    def get(self, request, round_id: int, version: int):
        return Response(serializers.VersionFiles(service.version(request.round, IDS, version)).data)


class WafVersion(DefenceView):
    @extend_schema(tags=TAGS, responses=serializers.VersionFiles, operation_id="defence_waf_version")
    def get(self, request, round_id: int, version: int):
        return Response(serializers.VersionFiles(service.version(request.round, WAF, version)).data)


class IdsTest(DefenceView):
    @extend_schema(tags=TAGS, request=serializers.IdsTest, responses=serializers.RuleTestResult,
                   operation_id="defence_ids_test")
    def post(self, request, round_id: int):
        asked = given(serializers.IdsTest, request.data)
        made = service.test_rules(request.round, request.player, IDS, asked["text"], asked.get("cases"))
        return Response(test_result(request.round, made))


class IdsTestResult(DefenceView):
    @extend_schema(tags=TAGS, responses=serializers.RuleTestResult, operation_id="defence_ids_test_result")
    def get(self, request, round_id: int, test_id: int):
        return Response(test_result(request.round, service.rule_test(request.round, IDS, test_id)))


class Waf(DefenceView):
    @extend_schema(tags=TAGS, responses=serializers.WafRead, operation_id="defence_waf")
    def get(self, request, round_id: int):
        return Response(serializers.WafRead(service.waf_files(request.round)).data)


class WafCheck(DefenceView):
    @extend_schema(tags=TAGS, request=serializers.WafFilesGiven, responses=serializers.RuleCheck,
                   operation_id="defence_waf_check")
    def post(self, request, round_id: int):
        asked = given(serializers.WafFilesGiven, request.data)
        return Response(serializers.RuleCheck(service.check_waf(request.round, asked["files"])).data)


class WafTest(DefenceView):
    @extend_schema(tags=TAGS, request=serializers.WafTest, responses=serializers.RuleTestResult,
                   operation_id="defence_waf_test")
    def post(self, request, round_id: int):
        asked = given(serializers.WafTest, request.data)
        made = service.test_rules(request.round, request.player, WAF, asked["files"], asked.get("cases"))
        return Response(test_result(request.round, made))


class WafTestResult(DefenceView):
    @extend_schema(tags=TAGS, responses=serializers.RuleTestResult, operation_id="defence_waf_test_result")
    def get(self, request, round_id: int, test_id: int):
        return Response(test_result(request.round, service.rule_test(request.round, WAF, test_id)))


class WafApply(DefenceView):
    @extend_schema(tags=TAGS, request=serializers.WafApply, responses=serializers.WafApplied,
                   operation_id="defence_waf_apply")
    def post(self, request, round_id: int):
        asked = given(serializers.WafApply, request.data)
        applied = service.apply_waf(request.round, asked["files"], asked["base_version"], request.player,
                                    asked.get("tested"))
        return Response(serializers.WafApplied(applied.rule_set).data)


class Terminal(DefenceView):
    reads_logs = False

    @extend_schema(tags=TAGS, responses=serializers.DefenceTerminal, operation_id="defence_terminal")
    def get(self, request, round_id: int):
        shown = defence_terminal.terminal(request.round, request.player)
        return Response(serializers.DefenceTerminal(auth.with_jump_host(request, shown)).data)


class IdsTerminal(DefenceView):
    reads_logs = False

    @extend_schema(tags=TAGS, responses=serializers.DefenceTerminal, operation_id="defence_ids_terminal")
    def get(self, request, round_id: int):
        shown = defence_terminal.terminal(request.round, request.player, defence_terminal.IDS)
        return Response(serializers.DefenceTerminal(auth.with_jump_host(request, shown)).data)


class Kibana(DefenceView):
    @extend_schema(tags=TAGS, responses=serializers.KibanaSpace, operation_id="defence_kibana")
    def get(self, request, round_id: int):
        return Response(serializers.KibanaSpace(kibana_gate.kibana_space(request.round)).data)

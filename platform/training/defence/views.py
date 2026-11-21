from drf_spectacular.utils import extend_schema
from rest_framework import status
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


def test_result(made) -> dict:
    return serializers.RuleTestResult({"test": made.pk, **made.result}).data


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


class IdsCheck(DefenceView):
    @extend_schema(tags=TAGS, request=serializers.Text, responses=serializers.RuleCheck, operation_id="defence_ids_check")
    def post(self, request, round_id: int):
        asked = given(serializers.Text, request.data)
        return Response(serializers.RuleCheck(service.check_ids(request.round, asked["text"])).data)


class IdsTest(DefenceView):
    @extend_schema(tags=TAGS, request=serializers.IdsTest, responses=serializers.RuleTestResult,
                   operation_id="defence_ids_test")
    def post(self, request, round_id: int):
        asked = given(serializers.IdsTest, request.data)
        made = service.test_rules(request.round, request.player, IDS, asked["text"], asked.get("cases"))
        return Response(test_result(made))


class IdsTestResult(DefenceView):
    @extend_schema(tags=TAGS, responses=serializers.RuleTestResult, operation_id="defence_ids_test_result")
    def get(self, request, round_id: int, test_id: int):
        return Response(test_result(service.rule_test(request.round, IDS, test_id)))


class IdsApply(DefenceView):
    @extend_schema(tags=TAGS, request=serializers.IdsApply, responses=serializers.IdsApplied,
                   operation_id="defence_ids_apply")
    def post(self, request, round_id: int):
        asked = given(serializers.IdsApply, request.data)
        applied = service.apply_ids(request.round, asked["text"], asked["base_version"], request.player,
                                    asked.get("tested"))
        return Response(serializers.IdsApplied({"version": applied.rule_set.version,
                                                "applied_at": applied.rule_set.applied_at,
                                                "same_as_tested": applied.rule_set.same_as_tested,
                                                "sensors": applied.sensors}).data)


class IdsDisabled(DefenceView):
    @extend_schema(tags=TAGS, responses=serializers.DisabledRule(many=True), operation_id="defence_ids_disabled")
    def get(self, request, round_id: int):
        return Response(serializers.DisabledRule(service.disabled(request.round), many=True).data)

    @extend_schema(tags=TAGS, request=serializers.Disable, responses={201: serializers.DisabledNow},
                   operation_id="defence_ids_disable")
    def post(self, request, round_id: int):
        asked = given(serializers.Disable, request.data)
        made = service.disable_rule(request.round, asked["sid"], asked["minutes"], asked["reason"])
        return Response(serializers.DisabledNow(made).data, status=status.HTTP_201_CREATED)


class IdsEnable(DefenceView):
    @extend_schema(tags=TAGS, responses={204: None}, operation_id="defence_ids_enable")
    def delete(self, request, round_id: int, sid: int):
        service.enable_rule(request.round, sid)
        return Response(status=status.HTTP_204_NO_CONTENT)


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
        return Response(test_result(made))


class WafTestResult(DefenceView):
    @extend_schema(tags=TAGS, responses=serializers.RuleTestResult, operation_id="defence_waf_test_result")
    def get(self, request, round_id: int, test_id: int):
        return Response(test_result(service.rule_test(request.round, WAF, test_id)))


class WafApply(DefenceView):
    @extend_schema(tags=TAGS, request=serializers.WafApply, responses=serializers.WafApplied,
                   operation_id="defence_waf_apply")
    def post(self, request, round_id: int):
        asked = given(serializers.WafApply, request.data)
        applied = service.apply_waf(request.round, asked["files"], asked["base_version"], request.player,
                                    asked.get("tested"))
        return Response(serializers.WafApplied(applied.rule_set).data)


class Terminal(DefenceView):
    @extend_schema(tags=TAGS, responses=serializers.DefenceTerminal, operation_id="defence_terminal")
    def get(self, request, round_id: int):
        return Response(serializers.DefenceTerminal(defence_terminal.terminal(request.round, request.player)).data)


class Kibana(DefenceView):
    @extend_schema(tags=TAGS, responses=serializers.KibanaSpace, operation_id="defence_kibana")
    def get(self, request, round_id: int):
        return Response(serializers.KibanaSpace(kibana_gate.kibana_space(request.round)).data)

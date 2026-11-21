from dataclasses import asdict

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from training.attack import actions as service
from training.attack import serializers
from training.round import access as auth

TAGS = ["attack"]


def given(serializer, data):
    found = serializer(data=data)
    found.is_valid(raise_exception=True)
    return found.validated_data


def answered(serializer, request, payload, code=status.HTTP_200_OK):
    return Response(serializer({**payload, "hp": asdict(service.hp(request.round))}).data, status=code)


class AttackView(APIView):
    authentication_classes = auth.ROUND_AUTHENTICATION
    permission_classes = [auth.IsPlayer("attack")]

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        player = getattr(request, "player", None)
        if player is None or player.side != "attack":
            return response
        block = service.hp(request.round)
        response["X-Origin"] = block.origin.ip if block.origin else ""
        response["X-Origin-HP"] = str(block.left)
        if response.status_code >= 400 and isinstance(response.data, dict) and "errors" in response.data:
            response.data["hp"] = serializers.HpBlock(block).data
        return response


class State(AttackView):
    @extend_schema(tags=TAGS, responses=serializers.AttackState, operation_id="attack_state")
    def get(self, request, round_id: int):
        return Response(serializers.AttackState(service.state(request.round)).data)


class Cases(AttackView):
    @extend_schema(tags=TAGS, responses=serializers.CaseEntry(many=True), operation_id="attack_cases")
    def get(self, request, round_id: int):
        return Response(serializers.CaseEntry(service.catalog(request.round), many=True).data)

    @extend_schema(tags=TAGS, request=serializers.FireCase, responses={202: serializers.Fired},
                   operation_id="attack_fire_case")
    def post(self, request, round_id: int):
        fired = service.fire_case(request.round, request.player, given(serializers.FireCase, request.data)["case"])
        return answered(serializers.Fired, request, asdict(fired), status.HTTP_202_ACCEPTED)


class Requests(AttackView):
    @extend_schema(tags=TAGS, request=serializers.SendRequest, responses=serializers.Sent,
                   operation_id="attack_send")
    def post(self, request, round_id: int):
        sent = service.send(request.round, request.player, **given(serializers.SendRequest, request.data))
        return answered(serializers.Sent, request, asdict(sent))


class Tools(AttackView):
    @extend_schema(tags=TAGS, responses=serializers.Tools, operation_id="attack_tools")
    def get(self, request, round_id: int):
        return answered(serializers.Tools, request, asdict(service.tool_list(request.round)))

    @extend_schema(tags=TAGS, request=serializers.StartTool, responses={202: serializers.Started},
                   operation_id="attack_start_tool")
    def post(self, request, round_id: int):
        asked = given(serializers.StartTool, request.data)
        started = service.start_tool(request.round, request.player, asked["tool"], list(asked["args"]))
        return answered(serializers.Started, request, asdict(started), status.HTTP_202_ACCEPTED)


class ToolRun(AttackView):
    @extend_schema(tags=TAGS, parameters=[serializers.OutputAfter], responses=serializers.RunPage,
                   operation_id="attack_tool_output")
    def get(self, request, round_id: int, run_id: int):
        after = given(serializers.OutputAfter, request.query_params)["after"]
        return answered(serializers.RunPage, request, asdict(service.tool_output(request.round, run_id, after)))

    @extend_schema(tags=TAGS, responses={204: None}, operation_id="attack_stop_tool")
    def delete(self, request, round_id: int, run_id: int):
        service.stop_tool(request.round, request.player, run_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class Loot(AttackView):
    @extend_schema(tags=TAGS, request=serializers.Loot, responses=serializers.Looted, operation_id="attack_loot")
    def post(self, request, round_id: int):
        looted = service.submit_loot(request.round, request.player, given(serializers.Loot, request.data)["value"])
        return answered(serializers.Looted, request, asdict(looted))


class NextOrigin(AttackView):
    @extend_schema(tags=TAGS, request=None, responses=serializers.NextOrigin, operation_id="attack_next_origin")
    def post(self, request, round_id: int):
        moved = service.next_origin(request.round, request.player)
        return Response(serializers.NextOrigin({"origin": moved.origin, "hp": moved}).data)


class Terminal(AttackView):
    @extend_schema(tags=TAGS, responses=serializers.AttackTerminal, operation_id="attack_terminal")
    def get(self, request, round_id: int):
        return answered(serializers.AttackTerminal, request, asdict(service.terminal(request.round, request.player)))

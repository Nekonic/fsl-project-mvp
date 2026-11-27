import json
from dataclasses import asdict

from drf_spectacular.extensions import OpenApiAuthenticationExtension
from drf_spectacular.utils import extend_schema
from rest_framework import renderers, status
from rest_framework.response import Response

from cr import errors
from sandbox import service as sandbox
from training.models import RoundRecord
from training.round import access as auth
from training.round import allocation as allocations
from training.round import bots as bot_runs
from training.round import debrief as debriefs
from training.round import lifecycle as service
from training.round import records
from training.round import serializers
from training.round.views_catch_up import CatchingUpView
from users import permissions as accounts
from users import permissions as users

TAGS = ["match"]
BOT_TAGS = ["bots"]
RECORD_TAGS = ["records"]
REFUSAL_HEADER = "X-Error-Code"
STAFF_TAGS = ["staff"]


def given(serializer, data):
    checked = serializer(data=data)
    checked.is_valid(raise_exception=True)
    return checked.validated_data


def shown_allocation(held, serializer=serializers.AllocationShown):
    held.ready = allocations.ready(held)
    return serializer(held).data


class PlayerTokenScheme(OpenApiAuthenticationExtension):
    target_class = auth.PlayerTokenAuthentication
    name = "player_token"

    def get_security_definition(self, auto_schema):
        return {"type": "http", "scheme": "bearer"}


class LauncherKeyScheme(OpenApiAuthenticationExtension):
    target_class = auth.LauncherAuthentication
    name = "launcher_key"

    def get_security_definition(self, auto_schema):
        return {"type": "http", "scheme": "bearer"}


class MatchView(CatchingUpView):
    authentication_classes = auth.ROUND_AUTHENTICATION


class Allocations(MatchView):
    permission_classes = [auth.Approved]

    @extend_schema(tags=TAGS, request=serializers.OpenAllocation, responses={201: serializers.AllocationShown},
                   operation_id="allocation_open")
    def post(self, request):
        held = allocations.open_allocation(request.user, given(serializers.OpenAllocation, request.data)["wargame"])
        return Response(shown_allocation(held), status=status.HTTP_201_CREATED)


class Allocation(MatchView):
    permission_classes = [auth.IsOperator]

    @extend_schema(tags=TAGS, responses=serializers.AllocationDetail, operation_id="allocation_read")
    def get(self, request, allocation_id: int):
        return Response(shown_allocation(request.allocation, serializers.AllocationDetail))


class Heartbeat(MatchView):
    permission_classes = [auth.OnAllocation]

    @extend_schema(tags=TAGS, request=None, responses=serializers.Expiry, operation_id="allocation_heartbeat")
    def post(self, request, allocation_id: int):
        return Response(serializers.Expiry(allocations.heartbeat(request.allocation)).data)


class CloseAllocation(MatchView):
    permission_classes = [auth.IsOperator]

    @extend_schema(tags=TAGS, request=None, responses=serializers.Closed, operation_id="allocation_close")
    def post(self, request, allocation_id: int):
        return Response(serializers.Closed(allocations.close_allocation(request.allocation)).data)


class AllocationRounds(MatchView):
    permission_classes = [auth.IsOperator]

    @extend_schema(tags=TAGS, request=serializers.CreateRound, responses={201: serializers.Created},
                   operation_id="round_create")
    def post(self, request, allocation_id: int):
        asked = given(serializers.CreateRound, request.data)
        made = service.create_round(request.allocation, asked["problem"], asked["matchup"], dict(asked["players"]),
                                    by=request.user)
        return Response(serializers.Created(made).data, status=status.HTTP_201_CREATED)


class Rounds(MatchView):
    permission_classes = [auth.Approved]

    @extend_schema(tags=TAGS, parameters=[serializers.RoundsQuery], responses=serializers.RoundLine(many=True),
                   operation_id="round_list")
    def get(self, request):
        asked = given(serializers.RoundsQuery, request.query_params)
        found = service.rounds_for(request.user, asked["mine"], asked["state"])
        return Response(serializers.RoundLine(found, many=True).data)


class Join(MatchView):
    permission_classes = [auth.Approved]

    @extend_schema(tags=TAGS, request=None, responses=serializers.Joined, operation_id="round_join")
    def post(self, request, round_id: int, side: str):
        player = service.join(service.round_of(round_id), side, request.user)
        return Response(serializers.Joined(player).data)


class Start(MatchView):
    permission_classes = [auth.IsOperator]

    @extend_schema(tags=TAGS, request=None, responses=serializers.PhaseShown, operation_id="round_start")
    def post(self, request, round_id: int):
        return Response(serializers.PhaseShown(service.start_round(service.round_of(round_id))).data)


class End(MatchView):
    permission_classes = [auth.IsOperator]

    @extend_schema(tags=TAGS, request=None, responses=serializers.Ended, operation_id="round_end")
    def post(self, request, round_id: int):
        return Response(serializers.Ended(service.end_round(service.round_of(round_id), "ended_by_operator")).data)


class RoundDetail(MatchView):
    permission_classes = [auth.InRound]

    @extend_schema(tags=TAGS, responses=serializers.RoundShown, operation_id="round_read")
    def get(self, request, round_id: int):
        operated = auth.operates(request, request.round.allocation)
        return Response(serializers.RoundShown(request.round, context={"operated": operated}).data)


class Score(MatchView):
    permission_classes = [auth.InRound]

    @extend_schema(tags=TAGS, parameters=[serializers.ScoreQuery], responses=serializers.Score,
                   operation_id="round_score")
    def get(self, request, round_id: int):
        asked = given(serializers.ScoreQuery, request.query_params)
        kept = records.kept_score(request.round) if request.round.phase == service.ENDED and not asked.get(
            "correlation") else None
        if kept is not None:
            return Response(serializers.Score({"pending": service.pending(request.round), **kept}).data)
        found = service.score_for(request.round, bool(request.user.is_staff),
                                  bool(request.user.is_staff) or (request.operator and not request.players),
                                  asked.get("correlation"))
        return Response(serializers.Score({"pending": service.pending(request.round), **service.shown_score(request.round, found)}).data)


class Topology(MatchView):
    permission_classes = [auth.InRound]

    @extend_schema(tags=TAGS, responses=serializers.Topology, operation_id="round_topology")
    def get(self, request, round_id: int):
        side = service.shown_side(request.players, request.operator)
        return Response(serializers.Topology(service.map_of(request.round, side)).data)


class SiteRequests(MatchView):
    permission_classes = [auth.InRound]

    @extend_schema(tags=TAGS, parameters=[serializers.SiteQuery], responses=serializers.SiteRequest(many=True),
                   operation_id="round_site_requests")
    def get(self, request, round_id: int):
        after = given(serializers.SiteQuery, request.query_params)["after"]
        return Response(serializers.SiteRequest(service.site_requests(request.round, request.players, after),
                                                many=True).data)


class TerminalAuth(MatchView):
    def handle_exception(self, exc):
        answer = super().handle_exception(exc)
        shown = answer.data.get("errors") if isinstance(answer.data, dict) else None
        if shown:
            answer[REFUSAL_HEADER] = shown[0]["code"]
        return answer

    def get(self, request, round_id: int):
        service.terminal_open(request.round)
        return Response(status=status.HTTP_204_NO_CONTENT)


class AttackTerminalAuth(TerminalAuth):
    permission_classes = [auth.IsPlayer("attack")]

    @extend_schema(tags=TAGS, responses={204: None}, operation_id="round_terminal_auth_attack")
    def get(self, request, round_id: int):
        return super().get(request, round_id)


class DefenceTerminalAuth(TerminalAuth):
    permission_classes = [auth.IsPlayer("defence")]

    @extend_schema(tags=TAGS, responses={204: None}, operation_id="round_terminal_auth_defence")
    def get(self, request, round_id: int):
        return super().get(request, round_id)


class IdsTerminalAuth(TerminalAuth):
    permission_classes = [auth.IsPlayer("defence")]

    @extend_schema(tags=TAGS, responses={204: None}, operation_id="round_terminal_auth_ids")
    def get(self, request, round_id: int):
        return super().get(request, round_id)


class Forfeit(MatchView):
    side = ""

    def get_permissions(self):
        return [auth.IsPlayer(self.side)()]

    def post(self, request, round_id: int):
        return Response(serializers.Ended(service.forfeit(request.round, request.player)).data)


class AttackForfeit(Forfeit):
    side = "attack"

    @extend_schema(tags=["attack"], request=None, responses=serializers.Ended, operation_id="attack_forfeit")
    def post(self, request, round_id: int):
        return super().post(request, round_id)


class DefenceForfeit(Forfeit):
    side = "defence"

    @extend_schema(tags=["defence"], request=None, responses=serializers.Ended, operation_id="defence_forfeit")
    def post(self, request, round_id: int):
        return super().post(request, round_id)


class Debrief(MatchView):
    permission_classes = [auth.InRound]

    @extend_schema(tags=TAGS, responses=serializers.Debrief, operation_id="round_debrief")
    def get(self, request, round_id: int):
        found = request.round
        if found.phase != service.ENDED:
            raise errors.Conflict(code="round_running")
        kept = RoundRecord.objects.filter(round_number=found.pk).first()
        return Response(serializers.Debrief(kept.debrief if kept and kept.debrief else debriefs.compose(found)).data)


class BotSteps(MatchView):
    permission_classes = [auth.Approved]

    @extend_schema(tags=TAGS, responses=serializers.StepLine(many=True), operation_id="bot_steps")
    def get(self, request):
        return Response(serializers.StepLine(bot_runs.step_lines(), many=True).data)


class Records(MatchView):
    permission_classes = [auth.Approved]

    @extend_schema(tags=RECORD_TAGS, parameters=[serializers.RecordsQuery],
                   responses=serializers.RecordLine(many=True), operation_id="records_list")
    def get(self, request):
        asked = given(serializers.RecordsQuery, request.query_params)
        return Response(serializers.RecordLine(records.mine(request.user, asked.get("problem")), many=True).data)


class Record(MatchView):
    permission_classes = [auth.Approved]

    @extend_schema(tags=RECORD_TAGS, responses=serializers.RecordShown, operation_id="record_read")
    def get(self, request, record_id: int):
        return Response(serializers.RecordShown(records.record(record_id, request.user)).data)


class LauncherView(MatchView):
    authentication_classes = (auth.LauncherAuthentication,)
    permission_classes = [auth.IsLauncher]


class BotRunClaim(LauncherView):
    @extend_schema(tags=BOT_TAGS, request=serializers.ClaimAsk, responses={200: serializers.Claimed, 204: None},
                   operation_id="bot_run_claim")
    def post(self, request):
        asked = given(serializers.ClaimAsk, request.data)
        claimed = bot_runs.claim(asked["restarted"], asked["launcher"])
        if claimed is None:
            return Response(status=status.HTTP_204_NO_CONTENT)
        return Response(serializers.Claimed(claimed).data)


class BotRunNotes(LauncherView):
    @extend_schema(tags=BOT_TAGS, request=serializers.NotesAsk, responses=serializers.NotesKept,
                   operation_id="bot_run_report")
    def post(self, request, run_id: int):
        asked = given(serializers.NotesAsk, request.data)
        return Response(serializers.NotesKept({"kept": bot_runs.report(bot_runs.run_of(run_id), asked["notes"])}).data)


class BotRunFinish(LauncherView):
    @extend_schema(tags=BOT_TAGS, request=serializers.FinishAsk, responses=serializers.RunShown,
                   operation_id="bot_run_finish")
    def post(self, request, run_id: int):
        asked = given(serializers.FinishAsk, request.data)
        run = bot_runs.finish(bot_runs.run_of(run_id), asked["exit"], asked["cost_usd"], asked["turns"],
                              asked["refusals"], asked["closing"])
        found = run.player.round
        found.refresh_from_db()
        if records.keep_when_due(found) is None:
            records.restate_bots(found)
        return Response(serializers.RunShown(run).data)


class StaffRange(MatchView):
    permission_classes = [accounts.IsStaff]

    @extend_schema(tags=STAFF_TAGS, responses=serializers.Range, operation_id="staff_range")
    def get(self, request):
        return Response(serializers.Range({"slots": [asdict(one) for one in allocations.slots()]}).data)


def shown_removed(found) -> Response:
    return Response(serializers.RemovedList({"removed": [asdict(one) for one in found]}).data)


class StaffFabric(MatchView):
    permission_classes = [accounts.IsStaff]

    @extend_schema(tags=STAFF_TAGS, request=None, responses=serializers.Fabric, operation_id="staff_fabric_build")
    def post(self, request):
        return Response(serializers.Fabric(asdict(sandbox.build_fabric())).data)

    @extend_schema(tags=STAFF_TAGS, responses=serializers.RemovedList, operation_id="staff_fabric_remove")
    def delete(self, request):
        return shown_removed(sandbox.remove_fabric())


class StaffLeftovers(MatchView):
    permission_classes = [accounts.IsStaff]

    @extend_schema(tags=STAFF_TAGS, responses=serializers.RemovedList, operation_id="staff_leftovers_remove")
    def delete(self, request):
        return shown_removed(sandbox.remove_leftovers())


class StaffPool(MatchView):
    permission_classes = [accounts.IsStaff]

    @extend_schema(tags=STAFF_TAGS, responses=serializers.Pool, operation_id="staff_pool")
    def get(self, request):
        return Response(serializers.Pool({"slots": [asdict(one) for one in sandbox.pool_standing()]}).data)

    @extend_schema(tags=STAFF_TAGS, request=None, responses=serializers.Range, operation_id="staff_pool_fill")
    def post(self, request):
        return Response(serializers.Range({"slots": [asdict(one) for one in allocations.fill_pool()]}).data)

    @extend_schema(tags=STAFF_TAGS, responses=serializers.RemovedList, operation_id="staff_pool_empty")
    def delete(self, request):
        return shown_removed(sandbox.empty_pool())


class RecordProbes(MatchView):
    permission_classes = [accounts.IsStaff]

    @extend_schema(tags=STAFF_TAGS, request=None, responses={202: serializers.ProbeAllocation},
                   operation_id="staff_probes_record")
    def post(self, request, wargame_id: str):
        held = service.record_probes(wargame_id, request.user)
        return Response(serializers.ProbeAllocation(held).data, status=status.HTTP_202_ACCEPTED)


class ProbeProgress(MatchView):
    permission_classes = [accounts.IsStaff]

    @extend_schema(tags=STAFF_TAGS, responses=serializers.ProbeProgress, operation_id="staff_probes_progress")
    def get(self, request, allocation_id: int):
        return Response(serializers.ProbeProgress(asdict(service.probe_progress(allocation_id))).data)


class Passthrough(renderers.BaseRenderer):
    media_type = "*/*"
    format = "site"
    charset = "utf-8"

    def render(self, data, accepted_media_type=None, renderer_context=None):
        if isinstance(data, str):
            return data.encode("utf-8")
        return json.dumps(data).encode("utf-8")


@extend_schema(exclude=True)
class SiteProxy(CatchingUpView):
    authentication_classes = (auth.PlayerTokenAuthentication, users.FramedSessionAuthentication)
    permission_classes = [auth.InRound]
    renderer_classes = [Passthrough]

    def answer(self, request, round_id: int, host: str, rest: str = ""):
        path = "/" + rest + (f"?{request.META['QUERY_STRING']}" if request.META.get("QUERY_STRING") else "")
        body = request.body.decode("utf-8", "replace") if request.body else None
        fetched = service.browse(request.round, request.players, request.method, host, path, dict(request.headers),
                                 body)
        kind = next((value for name, value in fetched.headers if name.lower() == "content-type"), "text/plain")
        answered = Response(fetched.body, status=fetched.status, content_type=kind)
        for name, value in fetched.headers:
            if name.lower() == "content-type":
                continue
            answered[name] = value
        if fetched.origins_left is not None:
            answered["X-Origins-Left"] = str(fetched.origins_left)
        return answered

    get = post = put = patch = delete = options = answer

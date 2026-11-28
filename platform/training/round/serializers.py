from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from training.models import MATCHUPS, NOTE_KINDS, PHASES, PLAYER_SIDES, REASONS, RUN_STATES
from training.round import bot_runs

STATES = [("", ""), ("open", "open"), ("joinable", "joinable")]
CORRELATIONS = [("marker", "marker"), ("window", "window")]
VERDICTS = [(verdict, verdict) for verdict in ("tp", "fn", "fp", "tn")]


class OpenAllocation(serializers.Serializer):
    wargame = serializers.CharField(max_length=64)


class PlayerLine(serializers.Serializer):
    side = serializers.ChoiceField(choices=PLAYER_SIDES)
    client = serializers.CharField()
    username = serializers.CharField(source="user.username", allow_null=True, read_only=True, default=None)
    bot_name = serializers.CharField()
    step = serializers.CharField()
    bot_run = serializers.SerializerMethodField()
    left_of_round_s = serializers.SerializerMethodField()

    @extend_schema_field(serializers.ChoiceField(choices=RUN_STATES, allow_null=True))
    def get_bot_run(self, player):
        run = bot_runs.latest_run(player)
        return run.status if run else None

    @extend_schema_field(serializers.IntegerField(allow_null=True))
    def get_left_of_round_s(self, player):
        run = bot_runs.latest_run(player)
        return bot_runs.left_of_round(run, player.round) if run else None


class RoundLine(serializers.Serializer):
    round = serializers.IntegerField(source="pk")
    wargame = serializers.CharField(source="allocation.wargame_id")
    problem = serializers.IntegerField(source="problem_id", allow_null=True)
    problem_title = serializers.CharField(source="problem.title", allow_null=True)
    matchup = serializers.CharField()
    phase = serializers.ChoiceField(choices=PHASES)
    players = PlayerLine(many=True, source="players.all")


class AllocationShown(serializers.Serializer):
    allocation = serializers.IntegerField(source="pk")
    wargame = serializers.CharField(source="wargame_id")
    slot = serializers.IntegerField(allow_null=True)
    ready = serializers.BooleanField()
    expires_at = serializers.DateTimeField()
    closed = serializers.DateTimeField(allow_null=True)


class AllocationDetail(AllocationShown):
    rounds = RoundLine(many=True, source="rounds.all")


class Expiry(serializers.Serializer):
    expires_at = serializers.DateTimeField()


class Closed(serializers.Serializer):
    closed = serializers.DateTimeField()


class BotAsk(serializers.Serializer):
    name = serializers.CharField(max_length=64, required=False)
    step = serializers.CharField(max_length=16, required=False)

    def to_internal_value(self, data):
        unknown = sorted(set(data) - set(self.fields)) if isinstance(data, dict) else []
        if unknown:
            raise serializers.ValidationError({unknown[0]: "not a field of a bot seat"}, code="unknown_field")
        return super().to_internal_value(data)

    def validate(self, attrs):
        if len(attrs) != 1:
            raise serializers.ValidationError({"step": "one of step and name"}, code="invalid_choice")
        return attrs


class PlayerAsk(serializers.Serializer):
    username = serializers.CharField(max_length=150, required=False)
    bot = BotAsk(required=False)
    open = serializers.BooleanField(required=False)

    def validate(self, attrs):
        if len(attrs) != 1:
            raise serializers.ValidationError({"username": "one of username, bot and open"}, code="invalid_choice")
        return attrs


class PlayersAsk(serializers.Serializer):
    attack = PlayerAsk(required=False)
    defence = PlayerAsk(required=False)


class CreateRound(serializers.Serializer):
    problem = serializers.IntegerField(required=False, allow_null=True, default=None)
    matchup = serializers.ChoiceField(choices=MATCHUPS)
    players = PlayersAsk()


class Created(serializers.Serializer):
    round = serializers.IntegerField(source="round.pk")
    players = PlayerLine(many=True, source="round.players.all")
    bot_tokens = serializers.DictField(child=serializers.CharField())


class RoundsQuery(serializers.Serializer):
    mine = serializers.BooleanField(required=False, default=False)
    state = serializers.ChoiceField(choices=STATES, required=False, default="")


class Joined(serializers.Serializer):
    player = serializers.IntegerField(source="pk")
    side = serializers.ChoiceField(choices=PLAYER_SIDES)


class PhaseShown(serializers.Serializer):
    phase = serializers.ChoiceField(choices=PHASES)


class Ended(serializers.Serializer):
    ended = serializers.DateTimeField()
    reason = serializers.ChoiceField(choices=REASONS, source="end_reason")


class RoundShown(serializers.Serializer):
    round = serializers.IntegerField(source="pk")
    allocation = serializers.IntegerField(source="allocation_id")
    wargame = serializers.CharField(source="allocation.wargame_id")
    problem = serializers.IntegerField(source="problem_id", allow_null=True)
    matchup = serializers.CharField()
    phase = serializers.ChoiceField(choices=PHASES)
    players = PlayerLine(many=True, source="players.all")
    started = serializers.DateTimeField(allow_null=True)
    ends_at = serializers.DateTimeField(allow_null=True)
    ended = serializers.DateTimeField(allow_null=True)
    end_reason = serializers.CharField()
    operated = serializers.SerializerMethodField()

    @extend_schema_field(serializers.BooleanField())
    def get_operated(self, found) -> bool:
        return bool(self.context.get("operated", False))


class ScoreQuery(serializers.Serializer):
    correlation = serializers.ChoiceField(choices=CORRELATIONS, required=False)


class LostObjective(serializers.Serializer):
    key = serializers.CharField()
    name = serializers.CharField()
    difficulty = serializers.IntegerField()
    detected = serializers.BooleanField()
    responded = serializers.BooleanField()
    response_seconds = serializers.FloatField(allow_null=True)
    attributed_marker = serializers.CharField(allow_null=True)


class KeptObjective(serializers.Serializer):
    key = serializers.CharField()
    name = serializers.CharField()
    difficulty = serializers.IntegerField()


class Objectives(serializers.Serializer):
    lost = LostObjective(many=True)
    kept = KeptObjective(many=True)
    weighted = serializers.FloatField()


class CaseLine(serializers.Serializer):
    case = serializers.CharField()
    title = serializers.CharField(required=False)
    verdict = serializers.ChoiceField(choices=VERDICTS)
    alerts = serializers.IntegerField()
    corroborated = serializers.BooleanField(allow_null=True)


class Totals(serializers.Serializer):
    tp = serializers.IntegerField()
    fp = serializers.IntegerField()
    fn = serializers.IntegerField()
    tn = serializers.IntegerField()


class Outcomes(serializers.Serializer):
    per_case = CaseLine(many=True)
    totals = Totals()
    note = serializers.CharField()


class OriginActivity(serializers.Serializer):
    ip = serializers.CharField()
    actions = serializers.IntegerField()
    alerts = serializers.IntegerField()
    refused = serializers.IntegerField()


class FreeActions(serializers.Serializer):
    by_origin = OriginActivity(many=True)


class Score(serializers.Serializer):
    pending = serializers.BooleanField()
    objectives = Objectives()
    outcomes = Outcomes()
    free_actions = FreeActions()


class Topology(serializers.Serializer):
    zones = serializers.ListField(child=serializers.JSONField())
    nodes = serializers.ListField(child=serializers.JSONField())
    edges = serializers.ListField(child=serializers.JSONField())


class SiteQuery(serializers.Serializer):
    after = serializers.IntegerField(required=False, default=0, min_value=0)


class SiteRequest(serializers.Serializer):
    id = serializers.IntegerField()
    at = serializers.DateTimeField()
    method = serializers.CharField()
    url = serializers.CharField()
    status = serializers.IntegerField()
    size = serializers.IntegerField()


class Refill(serializers.Serializer):
    state = serializers.CharField()
    reason = serializers.CharField()


class SlotLine(serializers.Serializer):
    slot = serializers.IntegerField()
    wargame = serializers.CharField()
    allocation = serializers.IntegerField(allow_null=True)
    refill = Refill()


class Range(serializers.Serializer):
    slots = SlotLine(many=True)


class Removed(serializers.Serializer):
    kind = serializers.CharField()
    id = serializers.CharField()


class RemovedList(serializers.Serializer):
    removed = Removed(many=True)


class Fabric(serializers.Serializer):
    present = serializers.ListField(child=serializers.CharField())
    clean = serializers.BooleanField()


class Server(serializers.Serializer):
    host = serializers.CharField()
    server = serializers.CharField()
    status = serializers.CharField()


class SlotStanding(serializers.Serializer):
    slot = serializers.IntegerField()
    wargame = serializers.CharField()
    servers = Server(many=True)
    blocked = serializers.ListField(child=serializers.CharField())
    failures = serializers.ListField(child=serializers.CharField())


class Pool(serializers.Serializer):
    slots = SlotStanding(many=True)


class ProbeAllocation(serializers.Serializer):
    allocation = serializers.IntegerField(source="pk")


class ProbeFailure(serializers.Serializer):
    case = serializers.CharField()
    code = serializers.CharField()


class ProbeProgress(serializers.Serializer):
    allocation = serializers.IntegerField()
    wargame = serializers.CharField()
    state = serializers.CharField()
    total = serializers.IntegerField()
    done = serializers.ListField(child=serializers.CharField())
    failed = ProbeFailure(many=True)


class PaceLine(serializers.Serializer):
    per_window = serializers.IntegerField()
    window_s = serializers.IntegerField()
    min_gap_s = serializers.IntegerField()


class AllowanceLine(serializers.Serializer):
    operations = serializers.ListField(child=serializers.CharField())
    cases = serializers.ListField(child=serializers.CharField())


class StepPlay(serializers.Serializer):
    model = serializers.CharField()
    family = serializers.CharField()
    pace = PaceLine()


class StepLine(serializers.Serializer):
    id = serializers.CharField()
    label = serializers.CharField()
    attack = StepPlay()
    defence = StepPlay()


class ClaimAsk(serializers.Serializer):
    restarted = serializers.BooleanField(required=False, default=False)
    launcher = serializers.DictField(required=False, default=dict)


class CardShown(serializers.Serializer):
    id = serializers.CharField()
    technique = serializers.CharField()
    name = serializers.CharField()
    quote = serializers.CharField()
    url = serializers.CharField()
    object_version = serializers.CharField()
    release = serializers.CharField()
    notice = serializers.CharField()


class StanceShown(CardShown):
    stance = serializers.CharField()


class PromptParts(serializers.Serializer):
    side = serializers.CharField()
    stance = serializers.CharField(allow_null=True)


class Claimed(serializers.Serializer):
    run = serializers.IntegerField()
    round = serializers.IntegerField()
    side = serializers.ChoiceField(choices=PLAYER_SIDES)
    step = serializers.CharField()
    token = serializers.CharField()
    model = serializers.CharField(source="play.model")
    budget_usd = serializers.FloatField(source="play.budget_usd")
    max_turns = serializers.IntegerField(source="play.max_turns")
    watch_s = serializers.IntegerField(source="play.watch_s", allow_null=True)
    pace = PaceLine(source="play.pace")
    allowance = AllowanceLine(source="play.allowance")
    card = StanceShown(allow_null=True)
    prompt = PromptParts()


class NoteAsk(serializers.Serializer):
    at = serializers.DateTimeField()
    kind = serializers.ChoiceField(choices=NOTE_KINDS)
    text = serializers.CharField(allow_blank=True, trim_whitespace=False)


class NotesAsk(serializers.Serializer):
    notes = NoteAsk(many=True)


class NotesKept(serializers.Serializer):
    kept = serializers.IntegerField()


class FinishAsk(serializers.Serializer):
    exit = serializers.CharField(max_length=32)
    cost_usd = serializers.FloatField(required=False, allow_null=True, default=None)
    turns = serializers.IntegerField(required=False, allow_null=True, default=None, min_value=0)
    refusals = serializers.IntegerField(required=False, default=0, min_value=0)
    closing = serializers.CharField(required=False, default="", allow_blank=True, trim_whitespace=False)


class RunShown(serializers.Serializer):
    run = serializers.IntegerField(source="pk")
    status = serializers.ChoiceField(choices=RUN_STATES)
    exit = serializers.CharField()


class Debrief(serializers.Serializer):
    round = serializers.IntegerField()
    matchup = serializers.CharField()
    pending = serializers.BooleanField()
    steps = serializers.DictField(child=serializers.CharField(allow_null=True))
    card = CardShown(allow_null=True)
    bots = serializers.ListField(child=serializers.JSONField())
    objectives = serializers.ListField(child=serializers.JSONField())
    timeline = serializers.ListField(child=serializers.JSONField())
    score = serializers.JSONField()


class RecordsQuery(serializers.Serializer):
    problem = serializers.IntegerField(required=False)


class RecordLine(serializers.Serializer):
    record = serializers.IntegerField(source="pk")
    round_number = serializers.IntegerField()
    wargame = serializers.CharField(source="wargame_id", allow_null=True)
    problem = serializers.IntegerField(source="problem_id", allow_null=True)
    problem_title = serializers.CharField(source="problem.title", allow_null=True)
    matchup = serializers.CharField()
    steps = serializers.DictField(child=serializers.CharField())
    started = serializers.DateTimeField(allow_null=True)
    ended = serializers.DateTimeField(allow_null=True)
    end_reason = serializers.CharField()
    incomplete = serializers.BooleanField()


class RecordShown(RecordLine):
    card = serializers.CharField()
    score = serializers.JSONField(allow_null=True)
    debrief = serializers.JSONField()
    bot = serializers.JSONField()

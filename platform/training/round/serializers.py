from rest_framework import serializers

from training.models import MATCHUPS, PHASES, REASONS, PLAYER_SIDES

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


class RoundLine(serializers.Serializer):
    round = serializers.IntegerField(source="pk")
    problem = serializers.IntegerField(source="problem_id")
    kind = serializers.CharField()
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
    name = serializers.CharField(max_length=64)


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
    problem = serializers.IntegerField()
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
    problem = serializers.IntegerField(source="problem_id")
    kind = serializers.CharField()
    matchup = serializers.CharField()
    phase = serializers.ChoiceField(choices=PHASES)
    players = PlayerLine(many=True, source="players.all")
    started = serializers.DateTimeField(allow_null=True)
    ends_at = serializers.DateTimeField(allow_null=True)
    ended = serializers.DateTimeField(allow_null=True)
    end_reason = serializers.CharField()


class ScoreQuery(serializers.Serializer):
    correlation = serializers.ChoiceField(choices=CORRELATIONS, required=False)


class LostObjective(serializers.Serializer):
    key = serializers.CharField()
    name = serializers.CharField()
    seen = serializers.BooleanField()
    attributed_marker = serializers.CharField(allow_null=True)


class KeptObjective(serializers.Serializer):
    key = serializers.CharField()
    name = serializers.CharField()


class Objectives(serializers.Serializer):
    lost = LostObjective(many=True)
    kept = KeptObjective(many=True)
    weighted = serializers.FloatField()


class CaseLine(serializers.Serializer):
    case = serializers.CharField()
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
    objectives = Objectives()
    outcomes = Outcomes()
    free_actions = FreeActions()
    posture_drift = serializers.BooleanField()


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

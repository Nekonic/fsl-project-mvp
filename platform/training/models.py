from django.conf import settings
from django.db import models

from domain.round_rules import BOT, END_REASONS, HUMAN, Matchup, Phase
from domain.types import ACTION_KINDS, CORRELATION_STRATEGIES, ENGINES

PROBLEM_KINDS = [("round", "round")]
PROBLEM_SIDES = [("attack", "attack"), ("defence", "defence"), ("both", "both")]


class Wargame(models.Model):
    id = models.CharField(max_length=32, primary_key=True)
    title = models.CharField(max_length=200)
    image = models.CharField(max_length=200)
    public_url = models.CharField(max_length=200)
    hosts = models.JSONField(default=list)
    objective_model = models.CharField(max_length=32)
    case_file = models.CharField(max_length=100)
    default_traffic = models.CharField(max_length=32, null=True, blank=True)

    class Meta:
        ordering = ["id"]


class Posture(models.Model):
    wargame = models.ForeignKey(Wargame, on_delete=models.PROTECT, related_name="postures")
    name = models.CharField(max_length=100)
    suricata_rules = models.TextField(blank=True, default="")
    waf_files = models.JSONField(default=dict)

    class Meta:
        ordering = ["wargame_id", "name"]
        constraints = [models.UniqueConstraint(fields=["wargame", "name"], name="one_posture_name_per_wargame")]


class Problem(models.Model):
    kind = models.CharField(max_length=8, choices=PROBLEM_KINDS)
    wargame = models.ForeignKey(Wargame, on_delete=models.PROTECT, related_name="problems")
    side = models.CharField(max_length=8, choices=PROBLEM_SIDES)
    title = models.CharField(max_length=200)
    summary = models.TextField(blank=True, default="")
    body = models.TextField(blank=True, default="")
    published = models.BooleanField(default=False)
    revision = models.PositiveIntegerField(default=1)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                               related_name="+")
    updated = models.DateTimeField(auto_now=True)
    start_posture = models.ForeignKey(Posture, on_delete=models.PROTECT, null=True, blank=True, related_name="+")

    class Meta:
        ordering = ["id"]


class RoundSetup(models.Model):
    problem = models.OneToOneField(Problem, on_delete=models.CASCADE, related_name="setup")
    matchups = models.JSONField(default=list)
    posture = models.ForeignKey(Posture, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    probe_cases = models.JSONField(default=list)
    objectives = models.JSONField(default=list)
    traffic = models.CharField(max_length=32, null=True, blank=True)
    benign_every_s = models.PositiveIntegerField(default=60)
    time_limit_s = models.PositiveIntegerField(null=True, blank=True)


class ProbeSet(models.Model):
    wargame = models.ForeignKey(Wargame, on_delete=models.CASCADE, related_name="probe_sets")
    image_digest = models.CharField(max_length=100)
    recorded_at = models.DateTimeField()
    cases = models.JSONField(default=dict)

    class Meta:
        ordering = ["-recorded_at"]
        constraints = [models.UniqueConstraint(fields=["wargame", "image_digest"], name="one_probe_set_per_image")]


PURPOSES = [(purpose, purpose) for purpose in ("round", "probe")]
ROUND_KINDS = [("round", "round")]
MATCHUPS = [(matchup.value, matchup.value) for matchup in Matchup]
PHASES = [(phase.value, phase.value) for phase in Phase]
PLAYER_SIDES = [(side, side) for side in ("attack", "defence")]
CLIENTS = [(client, client) for client in (HUMAN, BOT)]
REASONS = [(reason, reason) for reason in END_REASONS]


class Allocation(models.Model):
    wargame = models.ForeignKey(Wargame, on_delete=models.PROTECT, related_name="+")
    purpose = models.CharField(max_length=8, choices=PURPOSES)
    slot = models.PositiveIntegerField(null=True, blank=True)
    opened_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
                                  related_name="+")
    opened = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    closed = models.DateTimeField(null=True, blank=True)
    browse_marker = models.CharField(max_length=64, blank=True, default="")

    class Meta:
        ordering = ["id"]


class Round(models.Model):
    allocation = models.ForeignKey(Allocation, on_delete=models.CASCADE, related_name="rounds")
    problem = models.ForeignKey(Problem, on_delete=models.PROTECT, related_name="+")
    kind = models.CharField(max_length=8, choices=ROUND_KINDS)
    matchup = models.CharField(max_length=16, choices=MATCHUPS, blank=True, default="")
    phase = models.CharField(max_length=8, choices=PHASES, default=Phase.CREATED.value)
    snapshot = models.JSONField(default=dict)
    baseline = models.JSONField(null=True, blank=True)
    read_of = models.JSONField(default=dict)
    traffic = models.JSONField(default=dict)
    started = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)
    ended = models.DateTimeField(null=True, blank=True)
    end_reason = models.CharField(max_length=24, choices=REASONS, blank=True, default="")
    reading_since = models.DateTimeField(null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["id"]


class Player(models.Model):
    round = models.ForeignKey(Round, on_delete=models.CASCADE, related_name="players")
    side = models.CharField(max_length=8, choices=PLAYER_SIDES)
    client = models.CharField(max_length=8, choices=CLIENTS)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
                             related_name="+")
    bot_name = models.CharField(max_length=64, blank=True, default="")
    token_hash = models.CharField(max_length=64, null=True, blank=True, unique=True)
    token_revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["round_id", "side"]
        constraints = [models.UniqueConstraint(fields=["round", "side"], name="one_player_per_side")]


class CustomerRequest(models.Model):
    round = models.ForeignKey(Round, on_delete=models.CASCADE, related_name="customer_requests")
    marker = models.CharField(max_length=64)
    action = models.CharField(max_length=32)
    user = models.CharField(max_length=32)
    origin = models.CharField(max_length=32)
    source_ip = models.GenericIPAddressField(null=True, blank=True)
    method = models.CharField(max_length=8)
    path = models.TextField()
    status = models.PositiveSmallIntegerField()
    refused_by = models.CharField(max_length=8, blank=True, default="")
    sent_at = models.DateTimeField()
    elapsed_ms = models.PositiveIntegerField(default=0)
    benign_case = models.CharField(max_length=100, null=True, blank=True)

    class Meta:
        ordering = ["sent_at"]
        constraints = [models.UniqueConstraint(fields=["round", "marker"], name="one_customer_request_per_marker")]


ACTION_KIND_CHOICES = [(kind, kind) for kind in ACTION_KINDS]
CORRELATIONS = [(strategy, strategy) for strategy in CORRELATION_STRATEGIES]
STOPPED_BY = [(reason, reason) for reason in ("player", "origin_spent", "round_end")]


class Action(models.Model):
    round = models.ForeignKey(Round, on_delete=models.CASCADE, related_name="actions")
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="actions")
    kind = models.CharField(max_length=8, choices=ACTION_KIND_CHOICES)
    case_id = models.CharField(max_length=100, null=True, blank=True)
    malicious = models.BooleanField(null=True, blank=True)
    expect = models.CharField(max_length=200, null=True, blank=True)
    marker = models.CharField(max_length=64)
    correlation = models.CharField(max_length=8, choices=CORRELATIONS)
    source_ip = models.GenericIPAddressField(null=True, blank=True)
    started = models.DateTimeField()
    ended = models.DateTimeField()
    meta = models.JSONField(default=dict)

    class Meta:
        ordering = ["id"]
        constraints = [models.UniqueConstraint(fields=["round", "marker"], name="one_action_per_marker")]


class ToolRun(models.Model):
    action = models.OneToOneField(Action, on_delete=models.CASCADE, related_name="run")
    tool = models.CharField(max_length=32)
    argv = models.JSONField(default=list)
    started = models.DateTimeField()
    ended = models.DateTimeField(null=True, blank=True)
    exit_code = models.IntegerField(null=True, blank=True)
    stopped_by = models.CharField(max_length=16, choices=STOPPED_BY, null=True, blank=True)
    output_path = models.CharField(max_length=200)

    class Meta:
        ordering = ["id"]


SPENT_BY = [(reason, reason) for reason in ("deny", "limit_req", "player")]


class Origin(models.Model):
    round = models.ForeignKey(Round, on_delete=models.CASCADE, related_name="origins")
    origin_id = models.CharField(max_length=32)
    ip = models.GenericIPAddressField()
    label = models.CharField(max_length=100)
    spent_at = models.DateTimeField(null=True, blank=True)
    spent_by = models.CharField(max_length=16, choices=SPENT_BY, blank=True, default="")

    class Meta:
        ordering = ["id"]
        constraints = [models.UniqueConstraint(fields=["round", "ip"], name="one_row_per_origin")]


ENGINE_CHOICES = [(engine, engine) for engine in ENGINES]
RULE_SOURCES = [("setup", "setup"), ("console", "console"), ("terminal", "terminal")]


class RuleTest(models.Model):
    round = models.ForeignKey(Round, on_delete=models.CASCADE, related_name="rule_tests")
    player = models.ForeignKey(Player, on_delete=models.CASCADE, null=True, blank=True, related_name="rule_tests")
    engine = models.CharField(max_length=8, choices=ENGINE_CHOICES)
    sha = models.CharField(max_length=64)
    files = models.JSONField(default=dict)
    syntax_ok = models.BooleanField(default=False)
    result = models.JSONField(default=dict)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]


class RuleSet(models.Model):
    round = models.ForeignKey(Round, on_delete=models.CASCADE, related_name="rule_sets")
    engine = models.CharField(max_length=8, choices=ENGINE_CHOICES)
    version = models.PositiveIntegerField()
    files = models.JSONField(default=dict)
    sha = models.CharField(max_length=64)
    source = models.CharField(max_length=8, choices=RULE_SOURCES, default="console")
    applied_at = models.DateTimeField()
    tested = models.ForeignKey(RuleTest, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    player = models.ForeignKey(Player, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    same_as_tested = models.BooleanField(default=False)
    sensors = models.JSONField(default=list)

    class Meta:
        ordering = ["round_id", "engine", "version"]
        constraints = [models.UniqueConstraint(fields=["round", "engine", "version"], name="one_rule_set_per_version")]


class DisabledRule(models.Model):
    round = models.ForeignKey(Round, on_delete=models.CASCADE, related_name="disabled_rules")
    sid = models.PositiveBigIntegerField()
    original = models.TextField()
    reason = models.TextField(blank=True, default="")
    created = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    enabled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["id"]

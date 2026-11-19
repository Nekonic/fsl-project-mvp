from django.conf import settings
from django.db import models

KINDS = [("lesson", "lesson"), ("round", "round")]
SIDES = [("attack", "attack"), ("defence", "defence"), ("both", "both")]
PANES = [(pane, pane) for pane in ("kibana", "terminal_kali", "terminal_waf", "site", "map", "ids_rules", "waf",
                                   "alerts", "none")]


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
    crs_tuning = models.JSONField(default=dict)

    class Meta:
        ordering = ["wargame_id", "name"]
        constraints = [models.UniqueConstraint(fields=["wargame", "name"], name="one_posture_name_per_wargame")]


class Problem(models.Model):
    kind = models.CharField(max_length=8, choices=KINDS)
    wargame = models.ForeignKey(Wargame, on_delete=models.PROTECT, related_name="problems")
    side = models.CharField(max_length=8, choices=SIDES)
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


class Step(models.Model):
    problem = models.ForeignKey(Problem, on_delete=models.CASCADE, related_name="steps")
    order = models.PositiveIntegerField()
    body = models.TextField()
    opens = models.CharField(max_length=16, choices=PANES, default="none")
    check_spec = models.JSONField(default=dict, db_column="check")
    answer = models.JSONField(null=True, blank=True)
    hints = models.JSONField(default=list)

    class Meta:
        ordering = ["problem_id", "order"]
        constraints = [models.UniqueConstraint(fields=["problem", "order"], name="one_step_per_order")]


class RoundSetup(models.Model):
    problem = models.OneToOneField(Problem, on_delete=models.CASCADE, related_name="setup")
    matchups = models.JSONField(default=list)
    posture = models.ForeignKey(Posture, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    probe_cases = models.JSONField(default=list)
    objectives = models.JSONField(default=list)
    hp = models.JSONField(default=dict)
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

from django.db import models

from scoring.types import CaseRecord, DetectionRecord


class Session(models.Model):
    """훈련 세션 하나. 레드팀 실행 한 번에 해당한다."""

    scenario = models.CharField(max_length=128, default="juice-shop")
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-started_at"]


class Case(models.Model):
    """레드팀이 기록한 ground truth 한 건."""

    session = models.ForeignKey(Session, related_name="cases", on_delete=models.CASCADE)
    case_id = models.CharField(max_length=64, db_index=True)
    name = models.CharField(max_length=128)
    malicious = models.BooleanField()
    technique = models.CharField(max_length=64, blank=True, default="")
    correlation = models.CharField(max_length=16)
    source_ip = models.GenericIPAddressField(null=True, blank=True)
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField()
    meta = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["started_at"]
        unique_together = [("session", "case_id")]

    def to_record(self) -> CaseRecord:
        return CaseRecord(
            case_id=self.case_id,
            name=self.name,
            malicious=self.malicious,
            correlation=self.correlation,
            source_ip=self.source_ip,
            started_at=self.started_at,
            ended_at=self.ended_at,
        )


class Detection(models.Model):
    """Elasticsearch 에서 끌어온 경보 한 건."""

    session = models.ForeignKey(
        Session, related_name="detections", on_delete=models.CASCADE
    )
    detection_id = models.CharField(max_length=128)
    source = models.CharField(max_length=32)
    signature = models.TextField()
    severity = models.IntegerField(null=True, blank=True)
    timestamp = models.DateTimeField()
    src_ip = models.GenericIPAddressField(null=True, blank=True)
    marker = models.CharField(max_length=64, null=True, blank=True)
    raw = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["timestamp"]
        unique_together = [("session", "detection_id")]

    def to_record(self) -> DetectionRecord:
        return DetectionRecord(
            detection_id=self.detection_id,
            source=self.source,
            signature=self.signature,
            timestamp=self.timestamp,
            src_ip=self.src_ip,
            marker=self.marker,
        )


class RuleSet(models.Model):
    """Suricata 룰 파일의 한 버전."""

    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    applied_at = models.DateTimeField(null=True, blank=True)
    validation_output = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-created_at"]


class ScoreSnapshot(models.Model):
    """채점 결과 스냅샷."""

    session = models.ForeignKey(Session, related_name="scores", on_delete=models.CASCADE)
    tp = models.IntegerField()
    fp = models.IntegerField()
    fn = models.IntegerField()
    tn = models.IntegerField()
    precision = models.FloatField()
    recall = models.FloatField()
    f1 = models.FloatField()
    false_positive_rate = models.FloatField()
    warnings = models.JSONField(default=list)
    per_case = models.JSONField(default=list)
    computed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-computed_at"]

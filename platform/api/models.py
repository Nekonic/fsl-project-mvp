from django.db import models

from scoring.types import CaseRecord, DetectionRecord

class Session(models.Model):

    scenario = models.CharField(max_length=128, default="juice-shop")
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)
                                                                       
                                                                          
                                                                         
     
                                                                              
                                                                             
                                                                              
    baseline = models.JSONField(null=True, blank=True, default=None)
    truncated = models.BooleanField(default=False)
    read_of = models.JSONField(null=True, blank=True, default=None)

    class Meta:
        ordering = ["-started_at"]

class Case(models.Model):

    session = models.ForeignKey(Session, related_name="cases", on_delete=models.CASCADE)
    case_id = models.CharField(max_length=64, db_index=True)
    name = models.CharField(max_length=128)
    malicious = models.BooleanField()
    stage = models.CharField(max_length=32, blank=True, default="")
    technique = models.CharField(max_length=64, blank=True, default="")
    pattern = models.CharField(max_length=32, blank=True, default="")
    expect = models.CharField(max_length=128, null=True)
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

    session = models.ForeignKey(
        Session, related_name="detections", on_delete=models.CASCADE
    )
    detection_id = models.CharField(max_length=128)
    source = models.CharField(max_length=32)
    signature = models.TextField()
    severity = models.IntegerField(null=True, blank=True)
    timestamp = models.DateTimeField()
    src_ip = models.GenericIPAddressField(null=True, blank=True)
    src_host = models.CharField(max_length=128, blank=True, default="")
    dest_host = models.CharField(max_length=128, blank=True, default="")
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

class Objective(models.Model):

    session = models.ForeignKey(
        Session, related_name="objectives", on_delete=models.CASCADE
    )
    key = models.CharField(max_length=128)
    name = models.CharField(max_length=256)
    category = models.CharField(max_length=128, blank=True, default="")
    difficulty = models.IntegerField(default=1)
    achieved_at = models.DateTimeField()
    earliest = models.DateTimeField(null=True, blank=True)
    latest = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["achieved_at"]
        unique_together = [("session", "key")]

class RuleSet(models.Model):

    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    applied_at = models.DateTimeField(null=True, blank=True)
    validation_output = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-created_at"]

class Suppression(models.Model):

    sid = models.IntegerField()
    original = models.TextField()
    reason = models.CharField(max_length=256, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    restored_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]


from rest_framework import serializers

from telemetry.models import ENGINE_CHOICES


class Cursor(serializers.Serializer):
    after = serializers.IntegerField(min_value=0, default=0)


class Event(serializers.Serializer):
    id = serializers.IntegerField()
    kind = serializers.CharField()
    at = serializers.DateTimeField()
    seat_side = serializers.ChoiceField(choices=["attack", "defence"], allow_null=True)
    body = serializers.DictField()


class Page(serializers.Serializer):
    events = Event(many=True)
    next = serializers.IntegerField()


class AlertQuery(serializers.Serializer):
    after = serializers.IntegerField(min_value=0, default=0)
    engine = serializers.ChoiceField(choices=ENGINE_CHOICES, required=False)
    rule = serializers.CharField(required=False, max_length=64)
    src = serializers.IPAddressField(required=False)


class TrafficQuery(serializers.Serializer):
    after = serializers.CharField(required=False, default="", allow_blank=True, max_length=4096)


class Alert(serializers.Serializer):
    id = serializers.IntegerField(source="pk")
    time = serializers.DateTimeField(source="timestamp")
    engine = serializers.CharField()
    rule = serializers.CharField()
    signature = serializers.CharField()
    src_ip = serializers.CharField(allow_null=True)
    request_id = serializers.CharField(source="marker", allow_null=True)
    uri = serializers.CharField()
    blocked = serializers.BooleanField()


class Alerts(serializers.Serializer):
    alerts = Alert(many=True)
    next = serializers.IntegerField()


class TrafficOrigin(serializers.Serializer):
    ip = serializers.CharField()
    requests = serializers.IntegerField()
    refused = serializers.IntegerField()
    last_at = serializers.DateTimeField(allow_null=True)


class Traffic(serializers.Serializer):
    by_origin = TrafficOrigin(many=True)
    next = serializers.CharField()

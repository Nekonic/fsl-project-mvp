from rest_framework import serializers


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

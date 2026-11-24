from rest_framework import serializers


class Credentials(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(max_length=4096, trim_whitespace=False)


class SignUp(Credentials):
    username = serializers.RegexField(r"^[\w.@+-]+\Z", max_length=150)


class SignedIn(serializers.Serializer):
    user = serializers.CharField(source="username")


class SignedUp(serializers.Serializer):
    user = serializers.CharField(source="username")
    approved = serializers.BooleanField(source="is_active")


class CsrfIssued(serializers.Serializer):
    ok = serializers.BooleanField()


class Me(serializers.Serializer):
    user = serializers.CharField(source="username")
    is_staff = serializers.BooleanField()
    approved = serializers.BooleanField(source="is_active")
    site_origin = serializers.SerializerMethodField()

    def get_site_origin(self, _user) -> str:
        return self.context["site_origin"]


class Account(serializers.Serializer):
    username = serializers.CharField()
    approved = serializers.BooleanField(source="is_active")
    is_staff = serializers.BooleanField()
    joined = serializers.DateTimeField(source="date_joined")


class Block(serializers.Serializer):
    id = serializers.IntegerField()
    kind = serializers.ChoiceField(choices=["address", "fingerprint"])
    value = serializers.CharField()
    username = serializers.CharField()
    reason = serializers.CharField()
    failures = serializers.IntegerField()
    created = serializers.DateTimeField()
    until = serializers.DateTimeField()


class VpnProfile(serializers.Serializer):
    public_key = serializers.CharField()
    server_public_key = serializers.CharField()
    address = serializers.IPAddressField(protocol="IPv4")
    port = serializers.IntegerField()
    endpoint = serializers.SerializerMethodField()
    hosts = serializers.SerializerMethodField()
    created = serializers.DateTimeField()
    attached_round = serializers.IntegerField(allow_null=True)

    def get_endpoint(self, held) -> str:
        return self.context["endpoint"](held)

    def get_hosts(self, _held) -> list[str]:
        return list(self.context["hosts"])


class VpnIssued(VpnProfile):
    profile = serializers.SerializerMethodField()

    def get_profile(self, _held) -> str:
        return self.context["text"]


class VpnProfileRow(VpnProfile):
    username = serializers.CharField(source="user.username")
    user_id = serializers.IntegerField(source="user.pk")

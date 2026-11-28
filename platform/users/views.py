from urllib.parse import urlsplit
from drf_spectacular.authentication import SessionScheme
from drf_spectacular.utils import extend_schema
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from users import accounts as service
from users import permissions as users
from users import serializers
from users import vpn
from training.round import auth

ACCOUNTS = ["accounts"]
VPN_ISSUED = {201: serializers.VpnIssued}
STAFF = ["staff"]


class SignedInSession(SessionScheme):
    target_class = users.SessionAuthentication
    name = "cr_session"


class Csrf(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(tags=ACCOUNTS, responses=serializers.CsrfIssued, operation_id="auth_csrf")
    def get(self, request):
        service.issue_csrf(request)
        return Response(serializers.CsrfIssued({"ok": True}).data)


class Login(APIView):
    permission_classes = [users.CsrfChecked]

    @extend_schema(tags=ACCOUNTS, request=serializers.Credentials, responses=serializers.SignedIn,
                   operation_id="auth_login")
    def post(self, request):
        given = serializers.Credentials(data=request.data)
        given.is_valid(raise_exception=True)
        user = service.sign_in(request, **given.validated_data)
        return Response(serializers.SignedIn(user).data)


class SignUp(APIView):
    permission_classes = [users.CsrfChecked]

    @extend_schema(tags=ACCOUNTS, request=serializers.SignUp, responses={201: serializers.SignedUp},
                   operation_id="auth_signup")
    def post(self, request):
        given = serializers.SignUp(data=request.data)
        given.is_valid(raise_exception=True)
        user = service.sign_up(request, **given.validated_data)
        return Response(serializers.SignedUp(user).data, status=status.HTTP_201_CREATED)


class Logout(APIView):
    permission_classes = [users.CsrfChecked]

    @extend_schema(tags=ACCOUNTS, request=None, responses={204: None}, operation_id="auth_logout")
    def post(self, request):
        service.sign_out(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class Me(APIView):
    @extend_schema(tags=ACCOUNTS, responses=serializers.Me, operation_id="me")
    def get(self, request):
        return Response(serializers.Me(request.user).data)


class Users(APIView):
    permission_classes = [users.IsStaff]

    @extend_schema(tags=STAFF, responses=serializers.Account(many=True), operation_id="staff_users")
    def get(self, request):
        return Response(serializers.Account(service.users(), many=True).data)


class Approve(APIView):
    permission_classes = [users.IsStaff]

    @extend_schema(tags=STAFF, request=None, responses=serializers.Account, operation_id="staff_user_approve")
    def post(self, request, username: str):
        return Response(serializers.Account(service.approve(username)).data)


class Disable(APIView):
    permission_classes = [users.IsStaff]

    @extend_schema(tags=STAFF, request=None, responses=serializers.Account, operation_id="staff_user_disable")
    def post(self, request, username: str):
        return Response(serializers.Account(service.disable(username, by=request.user)).data)


class Blocks(APIView):
    permission_classes = [users.IsStaff]

    @extend_schema(tags=STAFF, responses=serializers.Block(many=True), operation_id="staff_blocks")
    def get(self, request):
        return Response(serializers.Block(service.standing_blocks(), many=True).data)


class Unblock(APIView):
    permission_classes = [users.IsStaff]

    @extend_schema(tags=STAFF, responses={204: None}, operation_id="staff_block_delete")
    def delete(self, request, block_id: int):
        service.unblock(block_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


def request_host(request) -> str:
    return urlsplit(f"//{request.get_host()}").hostname or ""


def vpn_context(request, **more) -> dict:
    host = request_host(request)
    return {"endpoint": lambda held: vpn.endpoint(held, host), "targets": vpn.targets, **more}


class VpnProfile(APIView):
    permission_classes = [auth.Approved]

    @extend_schema(tags=ACCOUNTS, request=None, responses=VPN_ISSUED, operation_id="vpn_profile_issue")
    def post(self, request):
        issued = vpn.issue(request.user, request_host(request))
        shown = serializers.VpnIssued(issued.profile, context=vpn_context(request, text=issued.text))
        return Response(shown.data, status=status.HTTP_201_CREATED)

    @extend_schema(tags=ACCOUNTS, responses=serializers.VpnProfile, operation_id="vpn_profile_read")
    def get(self, request):
        held = vpn.profile_of(request.user)
        return Response(serializers.VpnProfile(held, context=vpn_context(request)).data)

    @extend_schema(tags=ACCOUNTS, responses={204: None}, operation_id="vpn_profile_revoke")
    def delete(self, request):
        vpn.revoke(request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class VpnProfiles(APIView):
    permission_classes = [users.IsStaff]

    @extend_schema(tags=STAFF, responses=serializers.VpnProfileRow(many=True), operation_id="vpn_profiles_list")
    def get(self, request):
        return Response(serializers.VpnProfileRow(vpn.profiles(), many=True, context=vpn_context(request)).data)


class VpnProfileFor(APIView):
    permission_classes = [users.IsStaff]

    @extend_schema(tags=STAFF, responses={204: None}, operation_id="vpn_profile_revoke_for")
    def delete(self, request, user_id: int):
        vpn.revoke_for(user_id)
        return Response(status=status.HTTP_204_NO_CONTENT)

from drf_spectacular.authentication import SessionScheme
from drf_spectacular.utils import extend_schema
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts import serializers, service

ACCOUNTS = ["accounts"]
STAFF = ["staff"]


class SignedInSession(SessionScheme):
    target_class = service.SessionAuthentication
    name = "cr_session"


class Csrf(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(tags=ACCOUNTS, responses=serializers.CsrfIssued, operation_id="auth_csrf")
    def get(self, request):
        service.issue_csrf(request)
        return Response(serializers.CsrfIssued({"ok": True}).data)


class Login(APIView):
    permission_classes = [service.CsrfChecked]

    @extend_schema(tags=ACCOUNTS, request=serializers.Credentials, responses=serializers.SignedIn,
                   operation_id="auth_login")
    def post(self, request):
        given = serializers.Credentials(data=request.data)
        given.is_valid(raise_exception=True)
        user = service.sign_in(request, **given.validated_data)
        return Response(serializers.SignedIn(user).data)


class SignUp(APIView):
    permission_classes = [service.CsrfChecked]

    @extend_schema(tags=ACCOUNTS, request=serializers.SignUp, responses={201: serializers.SignedUp},
                   operation_id="auth_signup")
    def post(self, request):
        given = serializers.SignUp(data=request.data)
        given.is_valid(raise_exception=True)
        user = service.sign_up(request, **given.validated_data)
        return Response(serializers.SignedUp(user).data, status=status.HTTP_201_CREATED)


class Logout(APIView):
    permission_classes = [service.CsrfChecked]

    @extend_schema(tags=ACCOUNTS, request=None, responses={204: None}, operation_id="auth_logout")
    def post(self, request):
        service.sign_out(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class Me(APIView):
    @extend_schema(tags=ACCOUNTS, responses=serializers.Me, operation_id="me")
    def get(self, request):
        return Response(serializers.Me(request.user).data)


class Users(APIView):
    permission_classes = [service.IsStaff]

    @extend_schema(tags=STAFF, responses=serializers.Account(many=True), operation_id="staff_users")
    def get(self, request):
        return Response(serializers.Account(service.users(), many=True).data)


class Approve(APIView):
    permission_classes = [service.IsStaff]

    @extend_schema(tags=STAFF, request=None, responses=serializers.Account, operation_id="staff_user_approve")
    def post(self, request, username: str):
        return Response(serializers.Account(service.approve(username)).data)


class Disable(APIView):
    permission_classes = [service.IsStaff]

    @extend_schema(tags=STAFF, request=None, responses=serializers.Account, operation_id="staff_user_disable")
    def post(self, request, username: str):
        return Response(serializers.Account(service.disable(username, by=request.user)).data)


class Blocks(APIView):
    permission_classes = [service.IsStaff]

    @extend_schema(tags=STAFF, responses=serializers.Block(many=True), operation_id="staff_blocks")
    def get(self, request):
        return Response(serializers.Block(service.standing_blocks(), many=True).data)


class Unblock(APIView):
    permission_classes = [service.IsStaff]

    @extend_schema(tags=STAFF, responses={204: None}, operation_id="staff_block_delete")
    def delete(self, request, block_id: int):
        service.unblock(block_id)
        return Response(status=status.HTTP_204_NO_CONTENT)

from rest_framework import authentication, exceptions, permissions


class SessionAuthentication(authentication.SessionAuthentication):
    def enforce_csrf(self, request):
        try:
            super().enforce_csrf(request)
        except exceptions.PermissionDenied as refused:
            raise exceptions.PermissionDenied(code="csrf_failed") from refused


class CsrfChecked(permissions.BasePermission):
    def has_permission(self, request, view) -> bool:
        SessionAuthentication().enforce_csrf(request)
        return True


class IsStaff(permissions.BasePermission):
    code = "not_staff"

    def has_permission(self, request, view) -> bool:
        return bool(request.user and request.user.is_authenticated and request.user.is_staff)


class FramedSessionAuthentication(authentication.SessionAuthentication):
    def enforce_csrf(self, request):
        return None

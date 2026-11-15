import json

from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.views import redirect_to_login
from django.http import HttpResponse, JsonResponse
from django.middleware.csrf import get_token
from django.views.decorators.http import require_GET, require_POST

OPEN = frozenset({"/login/", "/api/auth/", "/api/auth/login/", "/auth-check/"})
REACHED_ONLY_THROUGH_THE_SITE_PORT = "/site-proxy/"


class SignedInOnly:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (
            request.path in OPEN
            or request.path.startswith(REACHED_ONLY_THROUGH_THE_SITE_PORT)
            or request.user.is_authenticated
        ):
            return self.get_response(request)
        if request.path.startswith("/api/"):
            return JsonResponse({"detail": "sign in first: POST /api/auth/login/"}, status=401)
        return redirect_to_login(request.get_full_path())


def csrf_refused(request, reason=""):
    return JsonResponse(
        {"detail": f"refused without a valid CSRF token ({reason}); GET /api/auth/ gives one"},
        status=403,
    )


def _signed_in(request):
    user = request.user
    return {
        "user": user.get_username() if user.is_authenticated else None,
        "csrf_token": get_token(request),
    }


@require_GET
def whoami(request):
    return JsonResponse(_signed_in(request))


@require_POST
def sign_in(request):
    try:
        given = json.loads(request.body or b"{}")
    except ValueError:
        given = None
    if not isinstance(given, dict):
        return JsonResponse({"detail": "send {\"username\": ..., \"password\": ...}"}, status=400)
    user = authenticate(request, username=str(given.get("username") or ""), password=str(given.get("password") or ""))
    if user is None:
        return JsonResponse({"detail": "wrong username or password"}, status=401)
    login(request, user)
    return JsonResponse(_signed_in(request))


@require_POST
def sign_out(request):
    logout(request)
    return JsonResponse(_signed_in(request))


def check(request):
    return HttpResponse(status=204 if request.user.is_authenticated else 401)


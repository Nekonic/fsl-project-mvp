import json

from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.views import redirect_to_login
from django.http import HttpResponse, JsonResponse
from django.middleware.csrf import get_token
from django.views.decorators.http import require_GET, require_POST

import kibana

OPEN = frozenset({
    "/login/", "/signup/", "/api/auth/", "/api/auth/login/", "/api/auth/signup/",
    "/auth-check/", "/auth-check/kibana/",
})
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
        "staff": user.is_authenticated and user.is_staff,
        "csrf_token": get_token(request),
    }


@require_GET
def whoami(request):
    return JsonResponse(_signed_in(request))


def _given(request):
    try:
        given = json.loads(request.body or b"{}")
    except ValueError:
        return None
    return given if isinstance(given, dict) else None


def _awaits_approval(username, password):
    waiting = get_user_model().objects.filter(username=username, is_active=False).first()
    return waiting is not None and waiting.check_password(password)


@require_POST
def sign_in(request):
    given = _given(request)
    if given is None:
        return JsonResponse({"detail": "send {\"username\": ..., \"password\": ...}"}, status=400)
    username, password = str(given.get("username") or ""), str(given.get("password") or "")
    user = authenticate(request, username=username, password=password)
    if user is None and _awaits_approval(username, password):
        return JsonResponse({"detail": "this account waits for an admin's approval", "pending": True}, status=403)
    if user is None:
        return JsonResponse({"detail": "wrong username or password"}, status=401)
    login(request, user)
    return JsonResponse(_signed_in(request))


@require_POST
def sign_up(request):
    given = _given(request)
    if given is None:
        return JsonResponse(
            {"detail": "send {\"username\": ..., \"password\": ..., \"password_confirm\": ...}"}, status=400)
    form = UserCreationForm({
        "username": str(given.get("username") or ""),
        "password1": str(given.get("password") or ""),
        "password2": str(given.get("password_confirm") or ""),
    })
    if not form.is_valid():
        refused = [(field, error) for field, errors in form.errors.as_data().items() for error in errors]
        return JsonResponse({
            "detail": " ".join(message for _, error in refused for message in error.messages),
            "errors": [{"field": field, "code": error.code} for field, error in refused],
        }, status=400)
    user = form.save(commit=False)
    user.is_active = False
    user.save()
    return JsonResponse({"user": user.get_username(), "pending": True}, status=201)


@require_POST
def sign_out(request):
    logout(request)
    return JsonResponse(_signed_in(request))


def check(request):
    return HttpResponse(status=204 if request.user.is_authenticated else 401)


def kibana_check(request):
    if not request.user.is_authenticated:
        return HttpResponse(status=401)
    answer = HttpResponse(status=204)
    answer["X-Kibana-Authorization"] = kibana.viewer_authorization()
    return answer

import json
import re
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.views import redirect_to_login
from django.core.cache import cache
from django.http import HttpResponse, JsonResponse
from django.middleware.csrf import get_token
from django.views.decorators.http import require_GET, require_POST

from api import blocks
from api.models import Session

SITE_SESSION = re.compile(r"^/site/(?P<session>\d+)/")
TERMINALS = "/vm-terminal/"
OPEN = frozenset({
    "/login/", "/signup/", "/api/auth/", "/api/auth/login/", "/api/auth/signup/", "/auth-check/",
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


SIGN_UPS_PER_ADDRESS_PER_HOUR = 5
PENDING_AT_MOST = 50


def _counted(key, seconds):
    cache.add(key, 0, seconds)
    try:
        return cache.incr(key)
    except ValueError:
        cache.set(key, 1, seconds)
        return 1


@require_POST
def sign_in(request):
    given = _given(request)
    if given is None:
        return JsonResponse({"detail": "send {\"username\": ..., \"password\": ...}"}, status=400)
    username, password = str(given.get("username") or ""), str(given.get("password") or "")
    refused = blocks.standing(request)
    if refused is not None:
        return refused
    user = authenticate(request, username=username, password=password)
    if user is None and _awaits_approval(username, password):
        return JsonResponse({"detail": "this account waits for an admin's approval", "pending": True}, status=403)
    if user is None:
        blocks.failed(request, username)
        return blocks.standing(request) or JsonResponse({"detail": "wrong username or password"}, status=401)
    blocks.succeeded(request)
    login(request, user)
    return JsonResponse(_signed_in(request))


@require_POST
def sign_up(request):
    given = _given(request)
    if given is None:
        return JsonResponse(
            {"detail": "send {\"username\": ..., \"password\": ..., \"password_confirm\": ...}"}, status=400)
    if get_user_model().objects.filter(is_active=False).count() >= PENDING_AT_MOST:
        return JsonResponse({"detail": f"{PENDING_AT_MOST} accounts already wait for approval; sign-up is closed for now",
                             "closed": True}, status=503)
    address = request.META.get("REMOTE_ADDR", "")
    if (cache.get(f"sign-ups:{address}") or 0) >= SIGN_UPS_PER_ADDRESS_PER_HOUR:
        return JsonResponse({"detail": "too many sign-ups from this address; try again in an hour",
                             "throttled": True}, status=429)
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
    _counted(f"sign-ups:{address}", 60 * 60)
    return JsonResponse({"user": user.get_username(), "pending": True}, status=201)


@require_POST
def sign_out(request):
    logout(request)
    return JsonResponse(_signed_in(request))


def _session_named_by(uri):
    parts = urlsplit(uri)
    site = SITE_SESSION.match(parts.path)
    if site:
        return site["session"]
    if parts.path.startswith(TERMINALS):
        named = parse_qs(parts.query).get("arg", [])
        return named[0] if len(named) == 1 and named[0].isdigit() else ""
    return None


def check(request):
    user = request.user
    if not user.is_authenticated:
        return HttpResponse(status=401)
    if user.is_staff:
        return HttpResponse(status=204)
    named = _session_named_by(request.headers.get("X-Original-URI", ""))
    if named is None:
        return HttpResponse(status=204)
    theirs = named != "" and Session.objects.filter(pk=int(named), owner=user).exists()
    return HttpResponse(status=204 if theirs else 403)


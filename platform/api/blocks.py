import hashlib
import ipaddress
import math
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db.models import Q
from django.http import JsonResponse
from django.utils import timezone

from api.models import SignInBlock

COUNTED_FOR = 60 * 60
TIERS = {
    "staff": {"failures": 3, "blocked_for": 60 * 60},
    "learner": {"failures": 10, "blocked_for": 15 * 60},
}
FINGERPRINT_ADDRESSES = 2
FINGERPRINTED = (
    "HTTP_USER_AGENT", "HTTP_ACCEPT", "HTTP_ACCEPT_LANGUAGE", "HTTP_ACCEPT_ENCODING",
    "HTTP_SEC_CH_UA", "HTTP_SEC_CH_UA_MOBILE", "HTTP_SEC_CH_UA_PLATFORM",
)
PLATFORM_HOST = ("127.0.0.0/8", "172.31.0.1/32")


def address(request):
    return request.META.get("REMOTE_ADDR", "")


def fingerprint(request):
    sent = "\n".join(request.META.get(name, "") for name in FINGERPRINTED)
    return hashlib.sha256(sent.encode()).hexdigest()[:32]


def from_the_platform_host(given):
    try:
        caller = ipaddress.ip_address(given)
    except ValueError:
        return False
    own = list(PLATFORM_HOST) + [host for host in settings.ALLOWED_HOSTS if _is_address(host)]
    return any(caller in ipaddress.ip_network(network, strict=False) for network in own)


def _is_address(host):
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def standing(request):
    if from_the_platform_host(address(request)):
        return None
    block = SignInBlock.objects.filter(until__gt=timezone.now()).filter(
        Q(kind="address", value=address(request)) | Q(kind="fingerprint", value=fingerprint(request))).first()
    if block is None:
        return None
    answer = JsonResponse({
        "detail": f"sign-in from this {block.kind} is blocked after failed sign-ins; try again later",
        "blocked_until": block.until.isoformat(), "blocked_by": block.kind,
    }, status=429)
    answer["Retry-After"] = str(math.ceil((block.until - timezone.now()).total_seconds()))
    return answer


def _tier(username):
    return "staff" if get_user_model().objects.filter(username=username, is_staff=True).exists() else "learner"


def _count(key):
    cache.add(key, 0, COUNTED_FOR)
    try:
        return cache.incr(key)
    except ValueError:
        cache.set(key, 1, COUNTED_FOR)
        return 1


def _seen_from(key, caller):
    seen = set(cache.get(key) or ()) | {caller}
    cache.set(key, sorted(seen), COUNTED_FOR)
    return len(seen)


def _block(kind, value, username, tier, failures):
    SignInBlock.objects.update_or_create(kind=kind, value=value, defaults={
        "username": username, "reason": f"{tier}-failures", "failures": failures,
        "until": timezone.now() + timedelta(seconds=TIERS[tier]["blocked_for"]),
    })


def failed(request, username):
    caller = address(request)
    if from_the_platform_host(caller):
        return
    tier, marked = _tier(username), fingerprint(request)
    limit = TIERS[tier]["failures"]
    by_address = _count(f"sign-in-failures:{tier}:address:{caller}")
    by_fingerprint = _count(f"sign-in-failures:{tier}:fingerprint:{marked}")
    addresses = _seen_from(f"sign-in-addresses:{tier}:{marked}", caller)
    if by_address >= limit:
        _block("address", caller, username, tier, by_address)
    if by_fingerprint >= limit and addresses >= FINGERPRINT_ADDRESSES:
        _block("fingerprint", marked, username, tier, by_fingerprint)


def succeeded(request):
    for tier in TIERS:
        cache.delete(f"sign-in-failures:{tier}:address:{address(request)}")

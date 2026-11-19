from __future__ import annotations

import hashlib
import ipaddress
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db.models import Q
from django.utils import timezone

from accounts.models import SignInBlock

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


def address(request) -> str:
    return request.META.get("REMOTE_ADDR", "")


def fingerprint(request) -> str:
    sent = "\n".join(request.META.get(name, "") for name in FINGERPRINTED)
    return hashlib.sha256(sent.encode()).hexdigest()[:32]


def is_address(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def from_the_platform_host(given: str) -> bool:
    if not is_address(given):
        return False
    caller = ipaddress.ip_address(given)
    own = [*PLATFORM_HOST, *(host for host in settings.ALLOWED_HOSTS if is_address(host))]
    return any(caller in ipaddress.ip_network(network, strict=False) for network in own)


def standing(request) -> SignInBlock | None:
    if from_the_platform_host(address(request)):
        return None
    return SignInBlock.objects.filter(until__gt=timezone.now()).filter(
        Q(kind="address", value=address(request)) | Q(kind="fingerprint", value=fingerprint(request))).first()


def tier(username: str) -> str:
    return "staff" if get_user_model().objects.filter(username=username, is_staff=True).exists() else "learner"


def counted(key: str, seconds: int = COUNTED_FOR) -> int:
    cache.add(key, 0, seconds)
    try:
        return cache.incr(key)
    except ValueError:
        cache.set(key, 1, seconds)
        return 1


def seen_from(key: str, caller: str) -> int:
    seen = set(cache.get(key) or ()) | {caller}
    cache.set(key, sorted(seen), COUNTED_FOR)
    return len(seen)


def block(kind: str, value: str, username: str, named_tier: str, failures: int) -> None:
    SignInBlock.objects.update_or_create(kind=kind, value=value, defaults={
        "username": username, "reason": f"{named_tier}-failures", "failures": failures,
        "until": timezone.now() + timedelta(seconds=TIERS[named_tier]["blocked_for"]),
    })


def failed(request, username: str) -> None:
    caller = address(request)
    if from_the_platform_host(caller):
        return
    named_tier, marked = tier(username), fingerprint(request)
    limit = TIERS[named_tier]["failures"]
    by_address = counted(f"sign-in-failures:{named_tier}:address:{caller}")
    by_fingerprint = counted(f"sign-in-failures:{named_tier}:fingerprint:{marked}")
    addresses = seen_from(f"sign-in-addresses:{named_tier}:{marked}", caller)
    if by_address >= limit:
        block("address", caller, username, named_tier, by_address)
    if by_fingerprint >= limit and addresses >= FINGERPRINT_ADDRESSES:
        block("fingerprint", marked, username, named_tier, by_fingerprint)


def succeeded(request) -> None:
    for named_tier in TIERS:
        cache.delete(f"sign-in-failures:{named_tier}:address:{address(request)}")


def lift(block_id: int) -> bool:
    lifted = SignInBlock.objects.filter(pk=block_id).first()
    if lifted is None:
        return False
    cache.delete_many([f"sign-in-failures:{named_tier}:{lifted.kind}:{lifted.value}" for named_tier in TIERS])
    lifted.delete()
    return True


def standing_blocks():
    return SignInBlock.objects.filter(until__gt=timezone.now())


def sign_ups_from(request) -> int:
    return cache.get(f"sign-ups:{address(request)}", 0)


def count_sign_up(request) -> None:
    counted(f"sign-ups:{address(request)}")

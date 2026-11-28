from __future__ import annotations

import math

from django.contrib import auth
from django.contrib.auth import get_user_model, password_validation
from django.core.exceptions import ValidationError
from django.middleware.csrf import get_token
from django.utils import timezone

from cr import errors
from users import blocks

SIGN_UPS_PER_ADDRESS_PER_HOUR = 5
PENDING_AT_MOST = 50


def issue_csrf(request) -> str:
    return get_token(request)


def refused_while_blocked(request) -> None:
    standing = blocks.standing(request)
    if standing is None:
        return
    left = max(1, math.ceil((standing.until - timezone.now()).total_seconds()))
    raise errors.TooMany(code="sign_in_blocked", params={
        "until": standing.until.isoformat(), "by": standing.kind, "retry_after": left,
    })


def awaits_approval(username: str, password: str) -> bool:
    waiting = get_user_model().objects.filter(username=username, is_active=False).first()
    return waiting is not None and waiting.check_password(password)


def sign_in(request, username: str, password: str):
    refused_while_blocked(request)
    user = auth.authenticate(request, username=username, password=password)
    if user is None and awaits_approval(username, password):
        raise errors.NotAPlayer(code="account_pending")
    if user is None:
        blocks.failed(request, username)
        refused_while_blocked(request)
        raise errors.NotSignedIn(code="wrong_credentials")
    blocks.succeeded(request)
    auth.login(request, user)
    return user


def sign_out(request) -> None:
    auth.logout(request)


def password_errors(username: str, password: str) -> list[errors.FieldError]:
    try:
        password_validation.validate_password(password, user=get_user_model()(username=username))
    except ValidationError as refused:
        return [errors.FieldError(path="password", code=error.code if error.code in errors.Invalid.codes else "invalid",
                                  params={key: value for key, value in (error.params or {}).items()
                                          if isinstance(value, int) and not isinstance(value, bool)})
                for error in refused.error_list]
    return []


def sign_up(request, username: str, password: str):
    users = get_user_model().objects
    if users.filter(is_active=False).count() >= PENDING_AT_MOST:
        raise errors.Unavailable(code="sign_ups_closed")
    if blocks.sign_ups_from(request) >= SIGN_UPS_PER_ADDRESS_PER_HOUR:
        raise errors.TooMany(code="sign_ups_throttled", params={"retry_after": blocks.COUNTED_FOR})
    refusals = []
    if users.filter(username__iexact=username).exists():
        refusals.append(errors.FieldError(path="username", code="username_taken"))
    refusals += password_errors(username, password)
    if refusals:
        raise errors.Invalid(errors=tuple(refusals))
    user = users.create_user(username=username, password=password, is_active=False)
    blocks.count_sign_up(request)
    return user


def user(username: str):
    found = get_user_model().objects.filter(username=username).first()
    if found is None:
        raise errors.NotFound(code="unknown_user")
    return found


def users():
    return get_user_model().objects.order_by("is_active", "-date_joined")


def approve(username: str):
    found = user(username)
    if not found.is_active:
        found.is_active = True
        found.save(update_fields=["is_active"])
    return found


def disable(username: str, by):
    found = user(username)
    if found.pk == by.pk:
        raise errors.Conflict(code="own_account")
    if found.is_active:
        found.is_active = False
        found.save(update_fields=["is_active"])
    return found


def standing_blocks():
    return blocks.standing_blocks()


def unblock(block_id: int) -> None:
    if not blocks.lift(block_id):
        raise errors.NotFound(code="unknown_block")

from __future__ import annotations

from django.contrib.auth import get_user_model

from accounts import blocks
from accounts.signin import CsrfChecked, IsStaff, SessionAuthentication, issue_csrf, sign_in, sign_out, sign_up
from cr import errors

__all__ = ["CsrfChecked", "IsStaff", "SessionAuthentication", "approve", "disable", "issue_csrf", "sign_in", "sign_out", "sign_up",
           "standing_blocks", "unblock", "user", "users"]


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

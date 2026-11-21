from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta

from django.utils import timezone

READ_ONLY_AFTER_END = timedelta(minutes=15)


def hashed(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue_token(seat) -> str:
    token = secrets.token_urlsafe(32)
    seat.token_hash, seat.token_revoked_at = hashed(token), None
    seat.save(update_fields=["token_hash", "token_revoked_at"])
    return token


def revoke_token(seat, at: datetime | None = None) -> None:
    seat.token_revoked_at = at or timezone.now()
    seat.save(update_fields=["token_revoked_at"])


def token_usable(seat, now: datetime) -> bool:
    if seat.token_revoked_at is not None and seat.token_revoked_at <= now:
        return False
    ended = seat.round.ended
    return ended is None or now <= ended + READ_ONLY_AFTER_END

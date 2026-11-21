from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta

from django.utils import timezone

READ_ONLY_AFTER_END = timedelta(minutes=15)


def hashed(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue_token(player) -> str:
    token = secrets.token_urlsafe(32)
    player.token_hash, player.token_revoked_at = hashed(token), None
    player.save(update_fields=["token_hash", "token_revoked_at"])
    return token


def revoke_token(player, at: datetime | None = None) -> None:
    player.token_revoked_at = at or timezone.now()
    player.save(update_fields=["token_revoked_at"])


def token_usable(player, now: datetime) -> bool:
    if player.token_revoked_at is not None and player.token_revoked_at <= now:
        return False
    ended = player.round.ended
    return ended is None or now <= ended + READ_ONLY_AFTER_END

from __future__ import annotations

from dataclasses import asdict

from cr import errors
from cr.config import configured
from domain.round_rules import Phase
from sandbox import access as jump
from sandbox import reach
from training.models import Round, Player

DEFENCE = "defence"
TERMINAL = "/vm-terminal/defence/{round}/"
ANALYST_ACCOUNT = "analyst"


def terminal(found: Round, player: Player) -> dict:
    if found.phase in (Phase.CREATED.value, Phase.STARTING.value):
        raise errors.Conflict(code="round_not_started")
    if found.phase == Phase.ENDED.value:
        raise errors.Conflict(code="round_closed")
    cfg = configured()
    reached = reach.range_of(found, cfg)
    access = jump.open_access(player.pk, reached.address(cfg.waf.role), reached.runner(cfg.waf.role),
                              ANALYST_ACCOUNT, cfg.jump)
    return {"ws_url": TERMINAL.format(round=found.pk),
            "ssh": {**asdict(access), "expires_at": found.ends_at or found.allocation.expires_at}}


def terminal_shell(player: Player) -> tuple[str, str]:
    grant = jump.granted(player.pk, configured().jump)
    if grant is None:
        raise errors.NotAPlayer()
    return grant.address, ANALYST_ACCOUNT


def revoke_terminal(found: Round) -> int:
    cfg = configured()

    def waf():
        return reach.range_of(found, cfg).runner(cfg.waf.role)

    revoked = sum(1 for player in Player.objects.filter(round=found, side=DEFENCE)
                  if jump.close_access(player.pk, waf, ANALYST_ACCOUNT, cfg.jump) is not None)
    if revoked:
        jump.end_account(waf(), ANALYST_ACCOUNT)
    return revoked

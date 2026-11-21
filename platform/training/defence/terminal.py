from __future__ import annotations

from dataclasses import asdict, dataclass

from cr import config, errors
from cr.config import configured
from domain.round_rules import Phase
from sandbox import access as jump
from sandbox import reach
from training.models import Round, Player

DEFENCE = "defence"
ANALYST_ACCOUNT = "analyst"
WAF, IDS = "", "ids"
TERMINAL = {WAF: "/vm-terminal/defence/{round}/", IDS: "/vm-terminal/ids/{round}/"}


@dataclass(frozen=True)
class Box:
    address: str
    runner: object


def box_of(found: Round, which: str, cfg: config.Config) -> Box:
    reached = reach.range_of(found, cfg)
    if which == WAF:
        return Box(reached.address(cfg.waf.role), reached.runner(cfg.waf.role))
    if not cfg.sensors:
        raise errors.Unavailable(code="sensor_unavailable")
    role = cfg.sensors[0].role
    return Box(reached.address(role), reached.node_runner(role))


def terminal(found: Round, player: Player, which: str = WAF) -> dict:
    if found.phase in (Phase.CREATED.value, Phase.STARTING.value):
        raise errors.Conflict(code="round_not_started")
    if found.phase == Phase.ENDED.value:
        raise errors.Conflict(code="round_closed")
    cfg = configured()
    box = box_of(found, which, cfg)
    access = jump.open_access(player.pk, box.address, box.runner, ANALYST_ACCOUNT, cfg.jump, which)
    return {"ws_url": TERMINAL[which].format(round=found.pk),
            "ssh": {**asdict(access), "expires_at": found.ends_at or found.allocation.expires_at}}


def terminal_shell(player: Player, which: str = WAF) -> tuple[str, str]:
    grant = jump.granted(player.pk, configured().jump, which)
    if grant is None:
        raise errors.NotAPlayer()
    return grant.address, ANALYST_ACCOUNT


def ids_terminal_shell(player: Player) -> tuple[str, str]:
    return terminal_shell(player, IDS)


def revoke_terminal(found: Round) -> int:
    cfg = configured()
    revoked = 0
    for which in TERMINAL:
        closed = sum(1 for player in Player.objects.filter(round=found, side=DEFENCE)
                     if jump.close_access(player.pk, lambda: box_of(found, which, cfg).runner, ANALYST_ACCOUNT,
                                          cfg.jump, which) is not None)
        if closed:
            jump.end_account(box_of(found, which, cfg).runner, ANALYST_ACCOUNT)
        revoked += closed
    return revoked

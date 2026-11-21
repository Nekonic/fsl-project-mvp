from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from cr import config, errors
from cr.config import configured
from domain.round_rules import Phase
from sandbox import definitions as declaration
from sandbox import kibana
from training.models import Round, Seat

DEFENCE = "defence"
GATEWAY_ROLE = "gateway"
DISCOVER = "{base}/s/{space}/app/discover"
FORBIDDEN, BAD_GATEWAY = 403, 502


@dataclass(frozen=True)
class GateAnswer:
    status: int
    headers: tuple[tuple[str, str], ...] = ()
    body: bytes = b""
    refused: str = ""

    @property
    def error(self) -> str:
        return "Forbidden" if self.status == FORBIDDEN else "Bad Gateway"


def index_of(found: Round, cfg: config.Config) -> str:
    return cfg.elastic.index_of(found.lease.slot or 0)


def gateway_name(cfg: config.Config) -> str:
    return declaration.read(Path(cfg.range.declaration), Path(cfg.range.source)).roles.get(GATEWAY_ROLE, "")


def prepare_kibana(found: Round, again: bool = True) -> bool:
    cfg = configured()
    return kibana.session_view_ready(index_of(found, cfg), gateway_name(cfg), cfg.kibana, again=again)


def kibana_space(found: Round) -> dict:
    cfg = configured()
    if not prepare_kibana(found, again=False):
        raise errors.Unavailable(code="kibana_unavailable")
    space = kibana.session_view_id(index_of(found, cfg))
    return {"space_url": DISCOVER.format(base=kibana.BASE_PATH, space=space)}


def kibana_spaces(user) -> dict[str, str] | None:
    if getattr(user, "is_staff", False):
        return None
    if getattr(user, "pk", None) is None:
        return {}
    cfg = configured()
    held = (Seat.objects.filter(user_id=user.pk, side=DEFENCE).exclude(round__phase=Phase.ENDED.value)
            .select_related("round__lease"))
    return {kibana.session_view_id(index): index for seat in held if (index := index_of(seat.round, cfg))}


def kibana_gate(user, method: str, uri: str, headers: Mapping[str, str], body: bytes) -> GateAnswer:
    spaces, asked = kibana_spaces(user), kibana.space_of(uri)
    if spaces is not None and asked is not None and asked not in spaces:
        return GateAnswer(status=FORBIDDEN, refused="kibana.refused.space")
    if kibana.refusal(method, uri, body, spaces):
        return GateAnswer(status=FORBIDDEN, refused="kibana.refused.call")
    try:
        status, kept, answered = kibana.forward(method, uri, headers, body, configured().kibana)
    except (OSError, ValueError):
        return GateAnswer(status=BAD_GATEWAY, refused="kibana.unanswered")
    return GateAnswer(status=status, headers=tuple(kept), body=answered)

from __future__ import annotations

from urllib.parse import urlsplit

from django.utils import timezone
from rest_framework import authentication, permissions

from cr import errors
from domain.round_rules import Phase
from training.models import Allocation, Round, Player
from users import permissions as users
from users.players import hashed, token_usable

BEARER = b"bearer"
NOT_STARTED = (Phase.CREATED.value, Phase.STARTING.value)


class BotPrincipal:
    is_authenticated = True
    is_active = True
    is_staff = False
    is_superuser = False
    is_anonymous = False
    pk = None
    id = None

    def __init__(self, player: Player):
        self.player_id = player.pk
        self.username = player.bot_name

    def __str__(self) -> str:
        return self.username


class PlayerTokenAuthentication(authentication.BaseAuthentication):
    def authenticate(self, request):
        given = authentication.get_authorization_header(request).split()
        if not given or given[0].lower() != BEARER:
            return None
        if len(given) != 2:
            raise errors.NotSignedIn()
        try:
            token = given[1].decode()
        except UnicodeDecodeError as undecodable:
            raise errors.NotSignedIn() from undecodable
        player = Player.objects.select_related("round", "user").filter(token_hash=hashed(token)).first()
        if player is None or not token_usable(player, timezone.now()):
            raise errors.NotSignedIn()
        if player.user is not None and not player.user.is_active:
            raise errors.NotSignedIn()
        return player.user or BotPrincipal(player), player

    def authenticate_header(self, request) -> str:
        return 'Bearer realm="player"'


ROUND_AUTHENTICATION = (PlayerTokenAuthentication, users.SessionAuthentication)


def round_of(request, view) -> Round:
    found = getattr(request, "round", None)
    if found is not None:
        return found
    found = Round.objects.select_related("allocation").filter(pk=view.kwargs.get("round_id")).first()
    if found is None:
        raise errors.NotFound(code="unknown_round")
    request.round = found
    return found


def signed_in(request) -> None:
    if not (request.user and request.user.is_authenticated):
        raise errors.NotSignedIn()


def players_of(request, found: Round) -> list[Player]:
    signed_in(request)
    if isinstance(request.auth, Player):
        return [request.auth] if request.auth.round_id == found.pk else []
    if isinstance(request.user, BotPrincipal):
        return []
    return list(Player.objects.filter(round=found, user=request.user))


def operates(request, allocation: Allocation) -> bool:
    if isinstance(request.auth, Player) or isinstance(request.user, BotPrincipal):
        return False
    return bool(request.user.is_staff or (allocation.opened_by_id is not None and allocation.opened_by_id == request.user.pk))


def refuse_write(found: Round) -> None:
    if found.phase in NOT_STARTED:
        raise errors.Conflict(code="round_not_started")
    if found.phase == Phase.ENDED.value:
        raise errors.Conflict(code="round_closed")


class SidePermission(permissions.BasePermission):
    side = ""

    def has_permission(self, request, view) -> bool:
        found = round_of(request, view)
        player = next((player for player in players_of(request, found) if player.side == self.side), None)
        if player is None:
            raise errors.NotAPlayer()
        request.player = player
        if request.method not in permissions.SAFE_METHODS:
            refuse_write(found)
        return True


def IsPlayer(side: str) -> type[SidePermission]:
    if side not in ("attack", "defence"):
        raise ValueError(f"no player side {side!r}")
    return type(f"Has{side.title()}Player", (SidePermission,), {"side": side})


class InRound(permissions.BasePermission):
    def has_permission(self, request, view) -> bool:
        found = round_of(request, view)
        request.players = players_of(request, found)
        request.operator = operates(request, found.allocation)
        if not request.players and not request.operator:
            raise errors.NotAPlayer()
        return True


def allocation_of(request, view) -> Allocation:
    if "allocation_id" not in view.kwargs:
        return round_of(request, view).allocation
    found = Allocation.objects.filter(pk=view.kwargs["allocation_id"]).first()
    if found is None:
        raise errors.NotFound(code="unknown_allocation")
    return found


class IsOperator(permissions.BasePermission):
    def has_permission(self, request, view) -> bool:
        signed_in(request)
        allocation = allocation_of(request, view)
        if not operates(request, allocation):
            raise errors.NotAPlayer(code="not_operator")
        request.allocation = allocation
        return True


class OnAllocation(permissions.BasePermission):
    def has_permission(self, request, view) -> bool:
        signed_in(request)
        allocation = allocation_of(request, view)
        request.allocation = allocation
        if operates(request, allocation):
            return True
        if isinstance(request.auth, Player):
            playing = request.auth.round.allocation_id == allocation.pk
            if playing and request.auth.round.phase == Phase.ENDED.value:
                raise errors.Conflict(code="round_closed")
        else:
            playing = not isinstance(request.user, BotPrincipal) and Player.objects.filter(
                round__allocation=allocation, user=request.user).exists()
        if not playing:
            raise errors.NotAPlayer()
        return True


class Approved(permissions.BasePermission):
    def has_permission(self, request, view) -> bool:
        signed_in(request)
        if isinstance(request.auth, Player) or isinstance(request.user, BotPrincipal):
            raise errors.NotAPlayer()
        return True


def with_jump_host(request, shown: dict) -> dict:
    ssh = shown["ssh"]
    if ssh.get("host"):
        return shown
    return {**shown, "ssh": {**ssh, "host": urlsplit(f"//{request.get_host()}").hostname or ""}}

from __future__ import annotations

from django.utils import timezone
from rest_framework import authentication, permissions

from cr import errors
from domain.round_rules import Phase
from training.models import Lease, Round, Seat
from users import permissions as users
from users.seats import hashed, token_usable

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

    def __init__(self, seat: Seat):
        self.seat_id = seat.pk
        self.username = seat.bot_name

    def __str__(self) -> str:
        return self.username


class SeatTokenAuthentication(authentication.BaseAuthentication):
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
        seat = Seat.objects.select_related("round", "user").filter(token_hash=hashed(token)).first()
        if seat is None or not token_usable(seat, timezone.now()):
            raise errors.NotSignedIn()
        if seat.user is not None and not seat.user.is_active:
            raise errors.NotSignedIn()
        return seat.user or BotPrincipal(seat), seat

    def authenticate_header(self, request) -> str:
        return 'Bearer realm="seat"'


ROUND_AUTHENTICATION = (SeatTokenAuthentication, users.SessionAuthentication)


def round_of(request, view) -> Round:
    found = getattr(request, "round", None)
    if found is not None:
        return found
    found = Round.objects.select_related("lease").filter(pk=view.kwargs.get("round_id")).first()
    if found is None:
        raise errors.NotFound(code="unknown_round")
    request.round = found
    return found


def signed_in(request) -> None:
    if not (request.user and request.user.is_authenticated):
        raise errors.NotSignedIn()


def seats_of(request, found: Round) -> list[Seat]:
    signed_in(request)
    if isinstance(request.auth, Seat):
        return [request.auth] if request.auth.round_id == found.pk else []
    if isinstance(request.user, BotPrincipal):
        return []
    return list(Seat.objects.filter(round=found, user=request.user))


def operates(request, lease: Lease) -> bool:
    if isinstance(request.auth, Seat) or isinstance(request.user, BotPrincipal):
        return False
    return bool(request.user.is_staff or (lease.opened_by_id is not None and lease.opened_by_id == request.user.pk))


def refuse_write(found: Round) -> None:
    if found.phase in NOT_STARTED:
        raise errors.Conflict(code="round_not_started")
    if found.phase == Phase.ENDED.value:
        raise errors.Conflict(code="round_closed")


class SidePermission(permissions.BasePermission):
    side = ""

    def has_permission(self, request, view) -> bool:
        found = round_of(request, view)
        seat = next((seat for seat in seats_of(request, found) if seat.side == self.side), None)
        if seat is None:
            raise errors.NotSeated()
        request.seat = seat
        if request.method not in permissions.SAFE_METHODS:
            refuse_write(found)
        return True


def HasSeat(side: str) -> type[SidePermission]:
    if side not in ("attack", "defence"):
        raise ValueError(f"no seat side {side!r}")
    return type(f"Has{side.title()}Seat", (SidePermission,), {"side": side})


class InRound(permissions.BasePermission):
    def has_permission(self, request, view) -> bool:
        found = round_of(request, view)
        request.seats = seats_of(request, found)
        request.operator = operates(request, found.lease)
        if not request.seats and not request.operator:
            raise errors.NotSeated()
        return True


def lease_of(request, view) -> Lease:
    if "lease_id" not in view.kwargs:
        return round_of(request, view).lease
    found = Lease.objects.filter(pk=view.kwargs["lease_id"]).first()
    if found is None:
        raise errors.NotFound(code="unknown_lease")
    return found


class IsOperator(permissions.BasePermission):
    def has_permission(self, request, view) -> bool:
        signed_in(request)
        lease = lease_of(request, view)
        if not operates(request, lease):
            raise errors.NotSeated(code="not_operator")
        request.lease = lease
        return True


class OnLease(permissions.BasePermission):
    def has_permission(self, request, view) -> bool:
        signed_in(request)
        lease = lease_of(request, view)
        request.lease = lease
        if operates(request, lease):
            return True
        if isinstance(request.auth, Seat):
            seated = request.auth.round.lease_id == lease.pk
            if seated and request.auth.round.phase == Phase.ENDED.value:
                raise errors.Conflict(code="round_closed")
        else:
            seated = not isinstance(request.user, BotPrincipal) and Seat.objects.filter(
                round__lease=lease, user=request.user).exists()
        if not seated:
            raise errors.NotSeated()
        return True


class Approved(permissions.BasePermission):
    def has_permission(self, request, view) -> bool:
        signed_in(request)
        if isinstance(request.auth, Seat) or isinstance(request.user, BotPrincipal):
            raise errors.NotSeated()
        return True

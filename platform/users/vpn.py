from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction

from cr import errors
from cr.config import configured
from sandbox import attacker
from sandbox import vpn as tunnel
from sandbox.substrate import slot_range
from users.models import VpnProfile

ATTACKER = attacker.ATTACKER_ROLE

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Issued:
    profile: VpnProfile
    text: str


def profile_of(user) -> VpnProfile:
    found = VpnProfile.objects.filter(user=user).first()
    if found is None:
        raise errors.NotFound(code="vpn_missing")
    return found


def profiles() -> list[VpnProfile]:
    return list(VpnProfile.objects.select_related("user"))


def endpoint_host(request_host: str) -> str:
    return configured().vpn.host or request_host


def free_port(config) -> int:
    taken = set(VpnProfile.objects.values_list("port", flat=True))
    port = next((port for port in tunnel.ports(config) if port not in taken), None)
    if port is None:
        raise errors.Conflict(code="vpn_ports_full")
    return port


def issue(user, request_host: str) -> Issued:
    cfg = configured()
    pc, server = tunnel.key_pair(), tunnel.key_pair()
    with transaction.atomic():
        held = VpnProfile.objects.select_for_update().filter(user=user).first()
        if held is None:
            port = free_port(cfg.vpn)
            held = VpnProfile(user=user, port=port, address=tunnel.address_for(port, cfg.vpn))
        held.public_key, held.server_public_key, held.server_private_key = pc.public, server.public, server.private
        try:
            held.save()
        except IntegrityError as taken:
            raise errors.Conflict(code="vpn_ports_full") from taken
    if held.attached_slot is not None:
        put_on_kali(held)
    shown = tunnel.profile_for(pc.private, held.port, held.server_public_key, endpoint_host(request_host),
                               Path(cfg.range.source), cfg.vpn)
    return Issued(profile=held, text=tunnel.profile_text(shown))


def revoke(user) -> None:
    held = profile_of(user)
    take_off_kali(held)
    held.delete()
    write_map()


def revoke_for(user_id: int) -> None:
    account = get_user_model().objects.filter(pk=user_id).first()
    if account is None:
        raise errors.NotFound(code="unknown_user")
    revoke(account)


def put_on_kali(held: VpnProfile) -> None:
    config = configured().vpn
    attacker.attach_peer(slot_range(held.attached_slot).runner(ATTACKER), held.server_private_key, held.public_key,
                         held.address, tunnel.kali_interface(config))


def take_off_kali(held: VpnProfile) -> None:
    if held.attached_slot is None:
        return
    try:
        attacker.detach_peer(slot_range(held.attached_slot).runner(ATTACKER))
    except (errors.DomainError, OSError) as failed:
        logger.warning("vpn profile %s: kali kept the tunnel: %s", held.pk, failed)


def attach(user, round_id: int, slot: int) -> bool:
    held = VpnProfile.objects.filter(user=user).first()
    if held is None:
        return False
    reached = slot_range(slot)
    held.attached_round, held.attached_slot = round_id, slot
    held.attached_address = attacker.kali_address(reached)
    held.save(update_fields=["attached_round", "attached_slot", "attached_address"])
    put_on_kali(held)
    write_map()
    return True


def detach(round_id: int) -> int:
    attached = list(VpnProfile.objects.filter(attached_round=round_id))
    for held in attached:
        take_off_kali(held)
    VpnProfile.objects.filter(pk__in=[held.pk for held in attached]).update(
        attached_round=None, attached_slot=None, attached_address=None)
    if attached:
        write_map()
    return len(attached)


def write_map() -> None:
    attached = VpnProfile.objects.exclude(attached_address=None).values_list("port", "attached_address")
    tunnel.write_port_map(dict(attached), configured().vpn)


def endpoint(held: VpnProfile, request_host: str) -> str:
    return f"{endpoint_host(request_host)}:{held.port}"


def targets(held: VpnProfile) -> tuple[tuple[str, str], ...]:
    if held.attached_slot is None:
        return ()
    attached = slot_range(held.attached_slot).wargame
    return tuple((wargame, url) for wargame, url in tunnel.target_urls(Path(configured().range.source))
                 if wargame == attached)

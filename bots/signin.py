from __future__ import annotations

import os

import httpx2

from bots.client import AuthenticatedClient, Client
from bots.client.api.accounts import auth_csrf, auth_login
from bots.client.models import CredentialsRequest

CSRF_COOKIE = "cr_csrf"
CSRF_HEADER = "X-CSRFToken"
DEFAULT_USER = "admin"
DEFAULT_PASSWORD = "123456"
TIMEOUT = 900.0


class Refused(RuntimeError):
    pass


def account() -> tuple[str, str]:
    return (os.environ.get("CR_ADMIN_USER") or DEFAULT_USER,
            os.environ.get("CR_ADMIN_PASSWORD") or DEFAULT_PASSWORD)


def stamping(http: httpx2.Client):
    def stamp(request: httpx2.Request) -> None:
        token = http.cookies.get(CSRF_COOKIE)
        if token:
            request.headers[CSRF_HEADER] = token

    return stamp


def anonymous(platform_url: str, timeout: float = TIMEOUT) -> Client:
    base = platform_url.rstrip("/")
    client = Client(base_url=base, timeout=httpx2.Timeout(timeout))
    http = httpx2.Client(base_url=base, timeout=httpx2.Timeout(timeout))
    http.event_hooks["request"] = [stamping(http)]
    return client.set_httpx_client(http)


def signed_in(platform_url: str, timeout: float = TIMEOUT) -> Client:
    client = anonymous(platform_url, timeout)
    user, password = account()
    try:
        auth_csrf.sync_detailed(client=client)
        answer = auth_login.sync_detailed(client=client, body=CredentialsRequest(username=user, password=password))
    except httpx2.HTTPError as unreachable:
        raise Refused(f"{platform_url} did not answer the sign-in: {unreachable}") from unreachable
    if answer.status_code != 200:
        raise Refused(f"{platform_url} refused the sign-in of {user} ({int(answer.status_code)}): "
                      f"{answer.content[:200]!r}; set CR_ADMIN_USER and CR_ADMIN_PASSWORD")
    return client


def playing(platform_url: str, token: str, timeout: float = TIMEOUT) -> AuthenticatedClient:
    return AuthenticatedClient(base_url=platform_url.rstrip("/"), token=token, timeout=httpx2.Timeout(timeout))

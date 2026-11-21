from __future__ import annotations

import os

import requests

from bots import rest

CSRF_COOKIE = "cr_csrf"
CSRF_HEADER = "X-CSRFToken"
DEFAULT_USER = "admin"
DEFAULT_PASSWORD = "123456"
TIMEOUT = 900.0


class Refused(RuntimeError):
    pass


class Platform(requests.Session):
    def __init__(self, base_url: str, timeout: float = TIMEOUT, token: str | None = None):
        super().__init__()
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        if token:
            self.headers["Authorization"] = f"Bearer {token}"

    def request(self, method, url, **named):
        csrf = self.cookies.get(CSRF_COOKIE)
        if csrf:
            named["headers"] = {CSRF_HEADER: csrf, **(named.get("headers") or {})}
        named.setdefault("timeout", self.timeout)
        return super().request(method, self.base_url + url if url.startswith("/") else url, **named)


def account() -> tuple[str, str]:
    return (os.environ.get("CR_ADMIN_USER") or DEFAULT_USER,
            os.environ.get("CR_ADMIN_PASSWORD") or DEFAULT_PASSWORD)


def anonymous(platform_url: str, timeout: float = TIMEOUT) -> Platform:
    return Platform(platform_url, timeout)


def signed_in(platform_url: str, timeout: float = TIMEOUT) -> Platform:
    session = anonymous(platform_url, timeout)
    user, password = account()
    try:
        rest.request(session, "auth_csrf")
        answer = rest.request(session, "auth_login", body={"username": user, "password": password})
    except requests.RequestException as unreachable:
        raise Refused(f"{platform_url} did not answer the sign-in: {unreachable}") from unreachable
    if answer.status_code != 200:
        raise Refused(f"{platform_url} refused the sign-in of {user} ({answer.status_code}): "
                      f"{answer.content[:200]!r}; set CR_ADMIN_USER and CR_ADMIN_PASSWORD")
    return session


def playing(platform_url: str, token: str, timeout: float = TIMEOUT) -> Platform:
    return Platform(platform_url, timeout, token)

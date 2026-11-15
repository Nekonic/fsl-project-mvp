from __future__ import annotations

import os

import requests

DEFAULT_USER = "admin"
DEFAULT_PASSWORD = "123456"
TIMEOUT = 30


class Refused(RuntimeError):
    pass


def account() -> tuple[str, str]:
    return (os.environ.get("CR_ADMIN_USER") or DEFAULT_USER,
            os.environ.get("CR_ADMIN_PASSWORD") or DEFAULT_PASSWORD)


def signed_in(platform_url: str, http: requests.Session | None = None) -> requests.Session:
    http = http or requests.Session()
    base = platform_url.rstrip("/")
    token = http.get(f"{base}/api/auth/", timeout=TIMEOUT).json()["csrf_token"]
    user, password = account()
    answer = http.post(f"{base}/api/auth/login/", json={"username": user, "password": password},
                       headers={"X-CSRFToken": token}, timeout=TIMEOUT)
    if not answer.ok:
        raise Refused(f"{base} refused the sign-in of {user} ({answer.status_code}): "
                      f"{answer.text[:200]}; set CR_ADMIN_USER and CR_ADMIN_PASSWORD")
    http.headers["X-CSRFToken"] = answer.json()["csrf_token"]
    return http

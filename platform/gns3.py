from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import requests
from django.conf import settings

TIMEOUT = (3, 10)
IMPORT_TIMEOUT = (3, 120)
BOOTSTRAP = "/static/web-ui/fsl-auditor.html"
ENGLISH = "en"
PORTABLE = "project.gns3"

class Unavailable(RuntimeError):
    pass

def drawn_in(language: str) -> Path:
    english = settings.FSL_TOPOLOGY
    return english if language == ENGLISH else english.with_suffix(f".{language}{english.suffix}")

def local(language: str = ENGLISH) -> dict:
    return json.loads(drawn_in(language).read_text())

def _api() -> str:
    return settings.FSL_GNS3_URL.rstrip("/") + "/v3"

def _signed(username: str, password: str) -> dict:
    signed = requests.post(f"{_api()}/access/users/authenticate", timeout=TIMEOUT,
                           json={"username": username, "password": password})
    signed.raise_for_status()
    return {"Authorization": f"Bearer {signed.json()['access_token']}"}

def _served(project_id: str) -> tuple[dict, str]:
    headers = _signed(settings.FSL_GNS3_USER, settings.FSL_GNS3_PASSWORD)
    found = requests.get(f"{_api()}/projects/{project_id}", headers=headers, timeout=TIMEOUT)
    found.raise_for_status()
    gns3file = requests.get(f"{_api()}/projects/{project_id}/gns3file", headers=headers, timeout=TIMEOUT)
    gns3file.raise_for_status()
    return gns3file.json(), found.json().get("status", "")

def project(language: str = ENGLISH, kept: dict | None = None) -> dict:
    kept = kept or local(language)
    if not settings.FSL_GNS3_URL:
        return {"source": "file", "status": "", "detail": "FSL_GNS3_URL is not set", "project": kept,
                "web_ui": None}
    try:
        served, status = _served(kept["project_id"])
    except (requests.RequestException, ValueError, KeyError) as exc:
        return {"source": "file", "status": "", "detail": f"GNS3 did not serve the project: {exc}"[:300],
                "project": kept, "web_ui": None}
    web_ui = {"port": settings.FSL_GNS3_WEB_PORT, "path": f"{BOOTSTRAP}?project={kept['project_id']}"}
    return {"source": "gns3", "status": status, "detail": "", "project": served,
            "web_ui": web_ui if status == "opened" else None}

def _admin() -> dict:
    password = settings.FSL_GNS3_ADMIN_PASSWORD
    if not password and settings.FSL_GNS3_ADMIN_PASSWORD_FILE.is_file():
        password = settings.FSL_GNS3_ADMIN_PASSWORD_FILE.read_text().strip()
    if not settings.FSL_GNS3_URL or not password:
        raise Unavailable("the GNS3 admin password is neither set nor readable, so no map can be loaded")
    try:
        return _signed(settings.FSL_GNS3_ADMIN_USER, password)
    except (requests.RequestException, ValueError, KeyError) as exc:
        raise Unavailable(f"GNS3 refused the admin sign-in: {exc}"[:300]) from exc

def _portable(document: dict) -> bytes:
    packed = io.BytesIO()
    with zipfile.ZipFile(packed, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(PORTABLE, json.dumps(document, indent=4, sort_keys=True))
    return packed.getvalue()

def _listed(headers: dict) -> list[dict]:
    listed = requests.get(f"{_api()}/projects", headers=headers, timeout=TIMEOUT)
    listed.raise_for_status()
    return listed.json()

def _gone(headers: dict, project_id: str) -> None:
    removed = requests.delete(f"{_api()}/projects/{project_id}", headers=headers, timeout=IMPORT_TIMEOUT)
    if removed.status_code not in (204, 404):
        removed.raise_for_status()

def publish(document: dict) -> str:
    headers = _admin()
    project_id = document["project_id"]
    try:
        if any(found["project_id"] == project_id for found in _listed(headers)):
            _gone(headers, project_id)
        made = requests.post(f"{_api()}/projects/{project_id}/import", headers=headers,
                             data=_portable(document), timeout=IMPORT_TIMEOUT)
        made.raise_for_status()
        kept = requests.put(f"{_api()}/projects/{project_id}", headers=headers, json={"auto_close": False},
                            timeout=IMPORT_TIMEOUT)
        kept.raise_for_status()
        opened = requests.post(f"{_api()}/projects/{project_id}/open", headers=headers, json={},
                               timeout=IMPORT_TIMEOUT)
        opened.raise_for_status()
        started = requests.post(f"{_api()}/projects/{project_id}/nodes/start", headers=headers, json={},
                                timeout=IMPORT_TIMEOUT)
        started.raise_for_status()
        return opened.json().get("status", "")
    except (requests.RequestException, ValueError) as exc:
        raise Unavailable(f"GNS3 did not load {document['name']}: {exc}"[:300]) from exc

def status(project_id: str) -> str:
    try:
        listed = _listed(_admin())
    except (Unavailable, requests.RequestException, ValueError):
        return ""
    return next((found.get("status", "") for found in listed if found.get("project_id") == project_id), "")

def remove_except(named: str, kept: set[str]) -> list[str]:
    headers = _admin()
    try:
        stale = [found["project_id"] for found in _listed(headers)
                 if found.get("name", "").startswith(named) and found["project_id"] not in kept]
        for project_id in stale:
            _gone(headers, project_id)
    except (requests.RequestException, ValueError) as exc:
        raise Unavailable(f"GNS3 did not list or remove the old maps: {exc}"[:300]) from exc
    return stale

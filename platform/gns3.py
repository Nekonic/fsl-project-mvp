from __future__ import annotations

import json

import requests
from django.conf import settings

TIMEOUT = (3, 10)
BOOTSTRAP = "/static/web-ui/fsl-auditor.html"

def local() -> dict:
    return json.loads(settings.FSL_TOPOLOGY.read_text())

def _served(project_id: str) -> tuple[dict, str]:
    api = settings.FSL_GNS3_URL.rstrip("/") + "/v3"
    signed = requests.post(f"{api}/access/users/authenticate", timeout=TIMEOUT,
                           json={"username": settings.FSL_GNS3_USER,
                                 "password": settings.FSL_GNS3_PASSWORD})
    signed.raise_for_status()
    headers = {"Authorization": f"Bearer {signed.json()['access_token']}"}
    found = requests.get(f"{api}/projects/{project_id}", headers=headers, timeout=TIMEOUT)
    found.raise_for_status()
    gns3file = requests.get(f"{api}/projects/{project_id}/gns3file", headers=headers, timeout=TIMEOUT)
    gns3file.raise_for_status()
    return gns3file.json(), found.json().get("status", "")

def project() -> dict:
    kept = local()
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

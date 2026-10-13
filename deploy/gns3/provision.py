import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import gns3server

API = "http://127.0.0.1:3080/v3"
HERE = Path(__file__).resolve().parent
WEB_UI = Path(gns3server.__file__).resolve().parent / "static" / "web-ui"
BOOTSTRAP = "fsl-auditor.html"
ADMIN = "admin"
AUDITOR_ROLE = "Auditor"
READY_WITHIN = 180
DATA = Path("/data")

def admin_password() -> str:
    given = os.environ.get("FSL_GNS3_ADMIN_PASSWORD")
    return given or (DATA / "admin-password").read_text().strip()

def auditor() -> dict:
    return {
        "username": os.environ.get("FSL_GNS3_AUDITOR_USER") or "learner",
        "password": os.environ.get("FSL_GNS3_AUDITOR_PASSWORD") or "fsl-auditor",
    }

def call(method: str, path: str, body=None, token: str = ""):
    request = urllib.request.Request(
        API + path, method=method,
        data=None if body is None else json.dumps(body).encode(),
        headers={"Content-Type": "application/json",
                 **({"Authorization": f"Bearer {token}"} if token else {})},
    )
    with urllib.request.urlopen(request, timeout=300) as answer:
        said = answer.read()
    return json.loads(said) if said else None

def ready() -> None:
    deadline = time.monotonic() + READY_WITHIN
    while time.monotonic() < deadline:
        try:
            call("GET", "/version")
            return
        except (urllib.error.URLError, ConnectionError):
            time.sleep(2)
    raise SystemExit(f"gns3-server did not answer on {API} within {READY_WITHIN}s")

def signed_in(username: str, password: str) -> str:
    return call("POST", "/access/users/authenticate",
                {"username": username, "password": password})["access_token"]

def the_auditor(token: str) -> None:
    wanted = auditor()
    users = {user["username"]: user for user in call("GET", "/access/users", token=token)}
    if wanted["username"] in users:
        user_id = users[wanted["username"]]["user_id"]
        call("PUT", f"/access/users/{user_id}", {"password": wanted["password"]}, token)
    else:
        user_id = call("POST", "/access/users", {**wanted, "full_name": "read-only learner"},
                       token)["user_id"]
    role_id = next(role["role_id"] for role in call("GET", "/access/roles", token=token)
                   if role["name"] == AUDITOR_ROLE)
    granted = any(ace.get("user_id") == user_id and ace["role_id"] == role_id and ace["path"] == "/"
                  for ace in call("GET", "/access/acl", token=token))
    if not granted:
        call("POST", "/access/acl", {"ace_type": "user", "path": "/", "propagate": True,
                                     "allowed": True, "user_id": user_id, "role_id": role_id}, token)
    print(f"fsl-gns3: {wanted['username']} holds {AUDITOR_ROLE} on /", flush=True)

def opened(token: str) -> None:
    for project in call("GET", "/projects", token=token):
        if project.get("status") == "opened":
            print(f"fsl-gns3: {project['name']} is open", flush=True)
            continue
        try:
            call("POST", f"/projects/{project['project_id']}/open", {}, token)
            print(f"fsl-gns3: opened {project['name']}", flush=True)
        except urllib.error.HTTPError as refused:
            print(f"fsl-gns3: {project['name']} stays closed: {refused.read().decode()[:400]}",
                  file=sys.stderr, flush=True)

def bootstrap() -> None:
    page = (HERE / "auditor.html").read_text().replace("__FSL_AUDITOR__", json.dumps(auditor()).replace("<", "\\u003c"))
    (WEB_UI / BOOTSTRAP).write_text(page)

def provision() -> None:
    ready()
    token = signed_in(ADMIN, admin_password())
    the_auditor(token)
    opened(token)

def api_key(name: str) -> None:
    token = signed_in(ADMIN, admin_password())
    made = call("POST", "/access/api-keys", {"name": name}, token)
    print(made["api_key"])

if __name__ == "__main__":
    asked = sys.argv[1:] or ["provision"]
    if asked[0] == "bootstrap":
        bootstrap()
    elif asked[0] == "provision":
        provision()
    elif asked[0] == "api-key" and len(asked) == 2:
        api_key(asked[1])
    else:
        raise SystemExit("usage: provision.py bootstrap | provision | api-key <name>")

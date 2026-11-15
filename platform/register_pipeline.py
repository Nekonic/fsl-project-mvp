import json
import os
import secrets
import time
import urllib.error
import urllib.request

import kibana

PIPELINE = f"{os.environ.get('CR_SOURCE', '/app')}/deploy/elastic/ingest-pipeline.json"
ATTEMPTS = 150
PAUSE = 2


def endpoint(base: str) -> str:
    return f"{base.rstrip('/')}/_ingest/pipeline/geoip"


def viewer_password() -> str:
    try:
        return kibana.viewer_password()
    except OSError:
        made = secrets.token_urlsafe(24)
        with open(os.open(kibana.VIEWER_PASSWORD_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w", encoding="utf-8") as kept:
            kept.write(made)
        return made


def puts(base: str, pipeline: bytes, password: str) -> list[tuple[str, bytes]]:
    base = base.rstrip("/")
    return [
        (endpoint(base), pipeline),
        (f"{base}/_security/role/{kibana.VIEWER_ROLE}", json.dumps(kibana.VIEWER_PRIVILEGES).encode()),
        (f"{base}/_security/user/{kibana.VIEWER}",
         json.dumps({"password": password, "roles": [kibana.VIEWER_ROLE]}).encode()),
    ]


def put(url: str, body: bytes) -> bool:
    request = urllib.request.Request(url, data=body, method="PUT", headers={"Content-Type": "application/json"})
    if kibana.ADMIN[1]:
        request.add_header("Authorization", kibana.basic(*kibana.ADMIN))
    try:
        with urllib.request.urlopen(request, timeout=5) as answer:
            return answer.status < 300
    except (urllib.error.URLError, OSError):
        return False


def main():
    base = os.environ.get("ELASTIC_URL", "http://elasticsearch:9200")
    try:
        body = open(PIPELINE, "rb").read()
    except OSError as exc:
        print(f"no pipeline file at {PIPELINE}: {exc}", flush=True)
        return

    left = puts(base, body, viewer_password())
    for _ in range(ATTEMPTS):
        left = [(url, sent) for url, sent in left if not put(url, sent)]
        if not left:
            print("geoip pipeline and Kibana viewer registered", flush=True)
            return
        time.sleep(PAUSE)

    print(f"could not register {', '.join(url for url, _ in left)}; ingest will not geolocate "
          "or Kibana will not open", flush=True)


if __name__ == "__main__":
    main()

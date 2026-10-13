import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

OBJECTS = f"{os.environ.get('FSL_SOURCE', '/app')}/deploy/kibana/objects.ndjson"
BASE_PATH = "/kibana"
DATA_VIEW = "fsl-logs"
ALERT_SEARCH = "fsl-alerts"
ALERTS_QUERY = 'event_type : "alert" or fsl_source : "modsecurity"'
ALERT_COLUMNS = (
    "fsl_source", "rule", "rule_id", "source_ip", "src_geo.country_name",
    "destination", "url", "status", "transaction.request.headers.X-FSL-Case",
)
SETTINGS = {"defaultRoute": f"/app/discover#/view/{ALERT_SEARCH}"}
ATTEMPTS = 60
NOT_READY = (502, 503, 504)
PAUSE = 5


class Refused(Exception):
    pass


def import_request(base, ndjson):
    boundary = uuid.uuid4().hex
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="objects.ndjson"\r\n'
        "Content-Type: application/ndjson\r\n\r\n"
    ).encode() + ndjson + f"\r\n--{boundary}--\r\n".encode()
    return urllib.request.Request(
        f"{base.rstrip('/')}/api/saved_objects/_import?overwrite=true",
        data=body, method="POST",
        headers={"kbn-xsrf": "fsl", "Content-Type": f"multipart/form-data; boundary={boundary}"},
    )


def settings_request(base):
    return urllib.request.Request(
        f"{base.rstrip('/')}/api/kibana/settings",
        data=json.dumps({"changes": SETTINGS}).encode(), method="POST",
        headers={"kbn-xsrf": "fsl", "Content-Type": "application/json"},
    )


def settle(base, ndjson, send):
    imported = send(import_request(base, ndjson))
    if not imported.get("success"):
        raise Refused(f"saved objects import failed: {imported.get('errors')}")
    send(settings_request(base))
    return imported.get("successCount", 0)


def send_json(request):
    with urllib.request.urlopen(request, timeout=10) as answer:
        return json.loads(answer.read() or b"{}")


def marked(marker):
    return f'transaction.request.headers.X-FSL-Case : "{marker}"'


def sensed(marker):
    return f'event_type : "alert" and http.request_headers.value : "{marker}"'


def sensed_http(marker):
    return f'event_type : "http" and http.request_headers.value : "{marker}"'


def rison(text):
    return "'" + text.replace("!", "!!").replace("'", "!'") + "'"


def discover_path(index, start, end, narrowed=None, everything=False):
    query = ALERTS_QUERY if not index else f"({ALERTS_QUERY}) and _index : {index}"
    if narrowed:
        query = f"{query} and ({narrowed})"
    if everything:
        query = " and ".join(part for part in (f"_index : {index}" if index else "",
                                               f"({narrowed})" if narrowed else "") if part) or "*"
    until = rison(end.isoformat()) if end else "now"
    global_state = f"(time:(from:{rison(start.isoformat())},to:{until}))"
    app_state = (
        f"(columns:!({','.join(ALERT_COLUMNS)}),"
        f"dataSource:(dataViewId:{DATA_VIEW},type:dataView),"
        f"query:(language:kuery,query:{rison(query)}),"
        "sort:!(!('@timestamp',desc)))"
    )
    safe = "()!:,'*@-._~"
    return (
        f"{BASE_PATH}/app/discover#/"
        f"?_g={urllib.parse.quote(global_state, safe=safe)}"
        f"&_a={urllib.parse.quote(app_state, safe=safe)}"
    )


def main():
    base = os.environ.get("KIBANA_URL", f"http://kibana:5601{BASE_PATH}")
    try:
        ndjson = open(OBJECTS, "rb").read()
    except OSError as exc:
        print(f"no saved objects at {OBJECTS}: {exc}", flush=True)
        return

    print(bring_up(base, ndjson, send_json, time.sleep), flush=True)


def bring_up(base, ndjson, send, pause):
    last = "could not reach Kibana"
    for _ in range(ATTEMPTS):
        try:
            count = settle(base, ndjson, send)
            return f"kibana: {count} saved objects imported, default route set"
        except Refused as exc:
            return f"kibana: {exc}"
        except urllib.error.HTTPError as exc:
            if exc.code not in NOT_READY:
                return f"kibana answered {exc.code} to {exc.url}: {exc.read()[:500].decode('utf-8', 'replace')}"
            last = f"Kibana still answered {exc.code}, not ready"
        except (urllib.error.URLError, OSError, ValueError):
            last = "could not reach Kibana"
        pause(PAUSE)
    return f"{last}; the data view, alert search and dashboard are missing"


if __name__ == "__main__":
    main()

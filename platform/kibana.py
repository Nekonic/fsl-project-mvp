import json
import os
import re
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
SETTINGS = {"defaultRoute": f"/app/discover#/view/{ALERT_SEARCH}", "metaFields": ["_source", "_id", "_score"]}
URL = os.environ.get("KIBANA_URL", "")
SESSION_VIEW_NAME = "Session logs"
SESSION_COLUMNS = (
    "log_source", "sensor", "event_type", "source_ip", "destination", "url", "status", "rule_id", "rule",
)
HIDDEN_FIELDS = (
    "_index", "fsl_*", "*X-FSL-Case*", "*x-fsl-case*", "log.*", "message", "agent.*", "ecs.*", "host", "host.*",
    "input.*", "error.*", "http.request_headers*",
)
MODULES = ("suricata", "modsecurity")
MARKER_HEADER = "x-fsl-case"
ATTEMPTS = 60
NOT_READY = (502, 503, 504)
PAUSE = 5
VIEW_RETRY = 60
VIEWS = {}


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


def status_request(base):
    return urllib.request.Request(f"{base.rstrip('/')}/api/status")


def settings_request(base):
    return urllib.request.Request(
        f"{base.rstrip('/')}/api/kibana/settings",
        data=json.dumps({"changes": SETTINGS}).encode(), method="POST",
        headers={"kbn-xsrf": "fsl", "Content-Type": "application/json"},
    )


def settle(base, ndjson, send):
    send(status_request(base))
    imported = send(import_request(base, ndjson))
    if not imported.get("success"):
        raise Refused(f"saved objects import failed: {imported.get('errors')}")
    send(settings_request(base))
    return imported.get("successCount", 0)


def send_json(request):
    with urllib.request.urlopen(request, timeout=10) as answer:
        return json.loads(answer.read() or b"{}")


def sensed_http(marker):
    return f'event_type : "http" and http.request_headers.value : "{marker}"'


def rison(text):
    return "'" + text.replace("!", "!!").replace("'", "!'") + "'"


def query(index="", narrowed="", alerts=True):
    return " and ".join(part for part in (
        f"({ALERTS_QUERY})" if alerts else "",
        f"_index : {index}" if index else "",
        f"({narrowed})" if narrowed else "",
    ) if part)


def recorded_by_an_engine(view):
    return (
        f"(meta:(alias:!n,disabled:!f,index:{rison(view)},key:log_source,negate:!f,type:exists,value:exists),"
        "query:(exists:(field:log_source)))"
    )


def discover_path(view, start, end, kql="", columns=SESSION_COLUMNS, engines_only=False):
    until = rison(end.isoformat()) if end else "now"
    global_state = f"(time:(from:{rison(start.isoformat())},to:{until}))"
    app_state = (
        f"(columns:!({','.join(columns)}),"
        f"dataSource:(dataViewId:{rison(view)},type:dataView),"
        f"filters:!({recorded_by_an_engine(view) if engines_only else ''}),"
        f"query:(language:kuery,query:{rison(kql)}),"
        "sort:!(!('@timestamp',desc)))"
    )
    safe = "()!:,'*@-._~"
    return (
        f"{BASE_PATH}/app/discover#/"
        f"?_g={urllib.parse.quote(global_state, safe=safe)}"
        f"&_a={urllib.parse.quote(app_state, safe=safe)}"
    )


def session_view_id(pattern):
    return "session-" + re.sub(r"[^a-z0-9]+", "-", pattern.lower()).strip("-")


def _value(field):
    return f"(doc.containsKey('{field}') && doc['{field}'].size() > 0 ? String.valueOf(doc['{field}'].value) : '')"


def _literal(text):
    return json.dumps(text)


def log_source_script():
    allowed = " || ".join(f"module == {_literal(module)}" for module in MODULES)
    return f"String module = {_value('fsl_source')}; if ({allowed}) {{ emit(module); }}"


def sensor_script(sensors, waf):
    shown = ", ".join(f"{_literal(host)}: {_literal(name)}" for host, name in sorted(sensors.items())) or ":"
    alone = sorted(set(sensors.values()))
    fallback = _literal(alone[0] if len(alone) == 1 else "")
    return (
        f"String module = {_value('fsl_source')}; "
        f"if (module == 'modsecurity') {{ emit({_literal(waf)}); }} "
        f"else if (module == 'suricata') {{ "
        f"String host = {_value('log.syslog.hostname')}; "
        "int dot = host.indexOf('.'); if (dot >= 0) { host = host.substring(0, dot); } "
        "int dash = host.lastIndexOf('-'); boolean slotted = dash > 0 && dash < host.length() - 1; "
        "for (int i = dash + 1; slotted && i < host.length(); ++i) { slotted = Character.isDigit(host.charAt(i)); } "
        "if (slotted) { host = host.substring(0, dash); } "
        f"Map shown = [{shown}]; "
        f"String name = shown.containsKey(host) ? (String) shown.get(host) : (host == '' ? {fallback} : ''); "
        "if (name != '') { emit(name); } }"
    )


def request_headers_script():
    return (
        "def http = params['_source']['http']; "
        "if (http instanceof Map && http['request_headers'] instanceof List) { "
        "for (def header : http['request_headers']) { "
        "if (header instanceof Map && header['name'] != null "
        f"&& !String.valueOf(header['name']).equalsIgnoreCase({_literal(MARKER_HEADER)})) {{ "
        "emit(String.valueOf(header['name']) + ': ' + String.valueOf(header['value'])); } } }"
    )


def shared_runtime(ndjson):
    for line in ndjson.splitlines():
        found = json.loads(line) if line.strip() else {}
        if found.get("id") == DATA_VIEW:
            return json.loads(found["attributes"]["runtimeFieldMap"])
    raise Refused(f"the saved objects hold no {DATA_VIEW} data view to take the runtime fields from")


def session_view(pattern, sensors, waf, runtime):
    fields = dict(runtime) | {
        "log_source": {"type": "keyword", "script": {"source": log_source_script()}},
        "sensor": {"type": "keyword", "script": {"source": sensor_script(sensors, waf)}},
        "request_headers": {"type": "keyword", "script": {"source": request_headers_script()}},
    }
    return {
        "type": "index-pattern",
        "id": session_view_id(pattern),
        "attributes": {
            "title": pattern,
            "name": SESSION_VIEW_NAME,
            "timeFieldName": "@timestamp",
            "allowNoIndex": True,
            "sourceFilters": json.dumps([{"value": hidden} for hidden in HIDDEN_FIELDS]),
            "runtimeFieldMap": json.dumps(fields),
        },
        "references": [],
        "managed": False,
        "coreMigrationVersion": "8.8.0",
        "typeMigrationVersion": "7.11.0",
    }


def ensure_session_view(pattern, sensors, waf, send=None):
    try:
        with open(OBJECTS, "rb") as objects:
            view = session_view(pattern, sensors, waf, shared_runtime(objects.read()))
        imported = (send or send_json)(import_request(URL, json.dumps(view).encode()))
        if not imported.get("success"):
            raise Refused(f"Kibana refused the data view for {pattern}: {imported.get('errors')}")
        return view["id"]
    except (Refused, OSError, ValueError, KeyError) as exc:
        print(f"kibana: no session data view for {pattern}: {exc}", flush=True)
        return None


def session_view_ready(pattern, sensors, waf, send=None, now=time.monotonic, again=False):
    made, at = VIEWS.get(pattern, (False, None))
    if again or not made and (at is None or now() - at >= VIEW_RETRY):
        made = ensure_session_view(pattern, sensors, waf, send) is not None
        VIEWS[pattern] = (made, now())
    return made


def main():
    base = URL or f"http://kibana:5601{BASE_PATH}"
    try:
        with open(OBJECTS, "rb") as objects:
            ndjson = objects.read()
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
            with exc:
                if exc.code not in NOT_READY:
                    return f"kibana answered {exc.code} to {exc.url}: {exc.read()[:500].decode('utf-8', 'replace')}"
            last = f"Kibana still answered {exc.code}, not ready"
        except (urllib.error.URLError, OSError, ValueError):
            last = "could not reach Kibana"
        pause(PAUSE)
    return f"{last}; the data view, alert search and dashboard are missing"


if __name__ == "__main__":
    main()

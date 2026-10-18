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
ALERTS_QUERY = 'event_type : "alert" or event.module : "modsecurity"'
ALERT_COLUMNS = (
    "event.module", "rule", "rule_id", "source_ip", "src_geo.country_name",
    "destination", "url", "status", "transaction.request.headers.X-Request-ID",
)
SETTINGS = {
    "defaultRoute": f"/app/discover#/view/{ALERT_SEARCH}", "metaFields": ["_source"], "dateFormat:tz": "Asia/Seoul",
}
SPACE_SETTINGS = {"defaultRoute": "/app/discover", "metaFields": ["_source"], "dateFormat:tz": "Asia/Seoul"}
SPACE_FEATURES_OFF = (
    "enterpriseSearch", "dashboard", "canvas", "maps", "ml", "logs", "visualize", "infrastructure", "apm", "uptime",
    "siem", "securitySolutionCases", "observabilityCases", "slo", "dev_tools", "advancedSettings", "indexPatterns",
    "filesManagement", "savedObjectsManagement", "savedObjectsTagging", "osquery", "actions", "generalCases",
    "guidedOnboardingFeature", "rulesSettings", "maintenanceWindow", "stackAlerts", "fleetv2", "fleet", "monitoring",
)
URL = os.environ.get("KIBANA_URL", "")
SESSION_VIEW_NAME = "logs-*"
SPACE_NAME = "Session logs"
SESSION_COLUMNS = ("event_type", "source_ip", "destination", "url", "status", "rule_id", "rule")
COLUMN_WIDTHS = {
    "@timestamp": 170, "event_type": 110, "source_ip": 130, "destination": 130, "status": 90, "rule_id": 110,
    "log_source": 110, "sensor": 110,
}
HIDDEN_FIELDS = (
    "_index", "event.*", "log.*", "message", "agent.*", "ecs.*", "host", "host.*",
    "input.*", "error.*", "http.request_headers*", "transaction.*", "flow_id", "tx_id", "pcap_cnt", "in_iface",
    "pkt_src", "community_id", "metadata.*",
)
SHOWN_AS_TEXT = ("src_port", "dest_port", "alert.signature_id", "alert.gid", "alert.rev")
REQUEST_HEADERS_SHOWN = (
    "Host", "User-Agent", "Accept", "Accept-Language", "Accept-Encoding", "Referer", "Cookie", "Content-Type",
    "Content-Length", "Origin", "X-Forwarded-For", "X-Forwarded-Proto", "X-Real-IP",
)
NO_RULE = "-"
MARKER_HEADER = "x-request-id"
ATTEMPTS = 60
NOT_READY = (502, 503, 504)
PAUSE = 5
VIEW_RETRY = 10
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


def settings_request(base, changes=None):
    return urllib.request.Request(
        f"{base.rstrip('/')}/api/kibana/settings",
        data=json.dumps({"changes": changes or SETTINGS}).encode(), method="POST",
        headers={"kbn-xsrf": "fsl", "Content-Type": "application/json"},
    )


def space_request(base, space, create):
    path = "/api/spaces/space" if create else f"/api/spaces/space/{space}"
    body = {"id": space, "name": SPACE_NAME, "disabledFeatures": list(SPACE_FEATURES_OFF)}
    return urllib.request.Request(
        f"{base.rstrip('/')}{path}", data=json.dumps(body).encode(), method="POST" if create else "PUT",
        headers={"kbn-xsrf": "fsl", "Content-Type": "application/json"},
    )


def space_base(base, space):
    return f"{base.rstrip('/')}/s/{space}"


def ensure_space(base, space, send):
    try:
        send(space_request(base, space, create=True))
    except urllib.error.HTTPError as exc:
        with exc:
            if exc.code != 409:
                raise
        send(space_request(base, space, create=False))


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


def query(narrowed="", alerts=True):
    return " and ".join(part for part in (
        f"({ALERTS_QUERY})" if alerts else "",
        f"({narrowed})" if narrowed else "",
    ) if part)


def discover_path(view, start, end, kql="", columns=SESSION_COLUMNS):
    until = rison(end.isoformat()) if end else "now"
    global_state = f"(time:(from:{rison(start.isoformat())},to:{until}))"
    app_state = (
        f"(columns:!({','.join(columns)}),"
        f"dataSource:(dataViewId:{rison(view)},type:dataView),"
        "filters:!(),"
        f"query:(language:kuery,query:{rison(kql)}),"
        "sort:!(!('@timestamp',desc)))"
    )
    safe = "()!:,'*@-._~"
    return (
        f"{BASE_PATH}/s/{view}/app/discover#/"
        f"?_g={urllib.parse.quote(global_state, safe=safe)}"
        f"&_a={urllib.parse.quote(app_state, safe=safe)}"
    )


def session_view_id(pattern):
    return "session-" + re.sub(r"[^a-z0-9]+", "-", pattern.lower()).strip("-")


def _value(field):
    return f"(doc.containsKey('{field}') && doc['{field}'].size() > 0 ? String.valueOf(doc['{field}'].value) : '')"


def _literal(text):
    return json.dumps(text)


def _after_first_dash(host):
    return host.split("-", 1)[-1]


def log_source_script():
    return f"String module = {_value('event.module')}; if (module != '') {{ emit(module); }}"


def sensor_script(sensors, waf):
    shown = ", ".join(f"{_literal(_after_first_dash(host))}: {_literal(name)}" for host, name in sorted(sensors.items())) or ":"
    alone = sorted(set(sensors.values()))
    fallback = _literal(alone[0] if len(alone) == 1 else "")
    return (
        f"String module = {_value('event.module')}; "
        f"if (module == 'modsecurity') {{ emit({_literal(waf)}); }} "
        f"else if (module == 'suricata') {{ "
        f"String host = {_value('log.syslog.hostname')}; "
        "int first = host.indexOf('-'); if (first >= 0) { host = host.substring(first + 1); } "
        "int dot = host.indexOf('.'); if (dot >= 0) { host = host.substring(0, dot); } "
        "int dash = host.lastIndexOf('-'); boolean numbered = dash > 0 && dash < host.length() - 1; "
        "for (int i = dash + 1; numbered && i < host.length(); ++i) { numbered = Character.isDigit(host.charAt(i)); } "
        "if (numbered) { host = host.substring(0, dash); } "
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


def header_field(name):
    return name.lower().replace("-", "_")


def request_header_script():
    shown = ", ".join(f"{_literal(name.lower())}: {_literal(header_field(name))}" for name in REQUEST_HEADERS_SHOWN)
    return (
        f"Map shown = [{shown}]; "
        "def http = params['_source']['http']; "
        "if (http instanceof Map && http['request_headers'] instanceof List) { "
        "for (def header : http['request_headers']) { "
        "if (header instanceof Map && header['name'] != null) { "
        "String key = String.valueOf(header['name']).toLowerCase(); "
        "if (shown.containsKey(key)) { emit((String) shown.get(key), String.valueOf(header['value'])); } } } } "
        "def transaction = params['_source']['transaction']; "
        "def sent = transaction instanceof Map && transaction['request'] instanceof Map "
        "? transaction['request']['headers'] : null; "
        "if (sent instanceof Map) { for (def entry : sent.entrySet()) { "
        "String key = String.valueOf(entry.getKey()).toLowerCase(); "
        "if (shown.containsKey(key)) { emit((String) shown.get(key), String.valueOf(entry.getValue())); } } }"
    )


def _each_waf_message(emitted):
    return (
        "def transaction = params['_source']['transaction']; "
        "def messages = transaction instanceof Map ? transaction['messages'] : null; "
        "int found = 0; "
        "if (messages instanceof List) { for (def message : messages) { if (message instanceof Map) { "
        "String id = message['details'] instanceof Map && message['details']['ruleId'] != null "
        "? String.valueOf(message['details']['ruleId']) : ''; "
        "String said = message['message'] != null ? String.valueOf(message['message']) : ''; "
        f"emit({emitted}); found++; }} }} }} "
        f"if (found == 0) {{ emit({_literal(NO_RULE)}); }}"
    )


def rule_id_script():
    return (
        f"String module = {_value('event.module')}; "
        f"if (module == 'modsecurity') {{ {_each_waf_message('id')} }} "
        f"else if (doc.containsKey('alert.signature_id') && doc['alert.signature_id'].size() > 0) {{ "
        "emit(String.valueOf(doc['alert.signature_id'].value)); }"
    )


def rule_script():
    paired = "(id + ' ' + said).trim()"
    return (
        f"String module = {_value('event.module')}; "
        f"if (module == 'modsecurity') {{ {_each_waf_message(paired)} }} "
        f"else if (doc.containsKey('alert.signature') && doc['alert.signature'].size() > 0) {{ "
        f"emit(({_value('alert.signature_id')} + ' ' + String.valueOf(doc['alert.signature'].value)).trim()); }}"
    )


def shared_runtime(ndjson):
    for line in ndjson.splitlines():
        found = json.loads(line) if line.strip() else {}
        if found.get("id") == DATA_VIEW:
            return json.loads(found["attributes"]["runtimeFieldMap"])
    raise Refused(f"the saved objects hold no {DATA_VIEW} data view to take the runtime fields from")


def session_view(pattern, sensors, waf, runtime):
    fields = dict(runtime) | {
        "rule": {"type": "keyword", "script": {"source": rule_script()}},
        "rule_id": {"type": "keyword", "script": {"source": rule_id_script()}},
        "log_source": {"type": "keyword", "script": {"source": log_source_script()}},
        "sensor": {"type": "keyword", "script": {"source": sensor_script(sensors, waf)}},
        "request_headers": {"type": "keyword", "script": {"source": request_headers_script()}},
        "request_header": {
            "type": "composite", "script": {"source": request_header_script()},
            "fields": {header_field(name): {"type": "keyword"} for name in REQUEST_HEADERS_SHOWN},
        },
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
            "fieldFormatMap": json.dumps({name: {"id": "string"} for name in SHOWN_AS_TEXT}),
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
        send = send or send_json
        ensure_space(URL, view["id"], send)
        imported = send(import_request(space_base(URL, view["id"]), json.dumps(view).encode()))
        if not imported.get("success"):
            raise Refused(f"Kibana refused the data view for {pattern}: {imported.get('errors')}")
        send(settings_request(space_base(URL, view["id"]), SPACE_SETTINGS))
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

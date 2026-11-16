import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

OBJECTS = f"{os.environ.get('CR_SOURCE', '/app')}/deploy/kibana/objects.ndjson"
BASE_PATH = "/kibana"
DATA_VIEW = "logs"
ALERT_SEARCH = "alerts"
ALERTS_QUERY = 'event_type : "alert" or event.module : "modsecurity" or event.module : "nginx"'
SESSION_COLUMNS = ("event_type", "source_ip", "destination", "url", "status", "rule_id", "rule")
ALERT_COLUMNS = SESSION_COLUMNS
SESSION_SEARCH = "events"
SESSION_SEARCH_TITLE = "Events"
SETTINGS = {
    "defaultRoute": f"/app/discover#/view/{ALERT_SEARCH}", "metaFields": ["_source"], "dateFormat:tz": "Asia/Seoul",
}
SPACE_SETTINGS = {
    "defaultRoute": f"/app/discover#/view/{SESSION_SEARCH}", "metaFields": ["_source"], "dateFormat:tz": "Asia/Seoul",
    "enableESQL": False, "defaultColumns": list(SESSION_COLUMNS), "bfetch:disable": True,
}
SPACE_FEATURES_OFF = (
    "enterpriseSearch", "dashboard", "canvas", "maps", "ml", "logs", "visualize", "infrastructure", "apm", "uptime",
    "siem", "securitySolutionCases", "observabilityCases", "slo", "dev_tools", "advancedSettings", "indexPatterns",
    "filesManagement", "savedObjectsManagement", "savedObjectsTagging", "osquery", "actions", "generalCases",
    "guidedOnboardingFeature", "rulesSettings", "maintenanceWindow", "stackAlerts", "fleetv2", "fleet", "monitoring",
)
URL = os.environ.get("KIBANA_URL", "")
SESSION_VIEW_NAME = "logs-*"
SPACE_NAME = "SOC"
SPACE_PREFIX = "soc-"
COLUMN_WIDTHS = {
    "@timestamp": 170, "event_type": 120, "source_ip": 140, "destination": 140, "status": 90, "rule_id": 110,
}
HIDDEN_FIELDS = (
    "_index", "event.*", "log.*", "message", "agent.*", "ecs.*", "host", "host.*",
    "input.*", "error.*", "http.request_headers*", "transaction.*", "flow_id", "tx_id", "pcap_cnt", "in_iface",
    "pkt_src", "community_id", "metadata.*", "src_ip", "dest_ip", "alert.signature", "alert.signature_id",
    "http.*", "data_stream.*",
)
SHOWN_AS_TEXT = ("src_port", "dest_port", "alert.gid", "alert.rev")
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
GATED = re.compile(r"/kibana/s/(?P<space>[a-z0-9-]+)/(?P<route>(?:api|internal)(?:/[A-Za-z0-9_=*-]+)+)")
DISCOVER_READS = {
    "GET": frozenset({
        "api/banners/info", "api/licensing/info", "api/saved_objects_tagging/tags",
        "api/index_patterns/has_user_index_pattern", "internal/data_views/has_data_views",
        "internal/spaces/_active_space", "internal/telemetry/config",
        "internal/kibana/settings", "internal/security/me", "internal/security/session",
        "internal/security/user_profile", "internal/security/security_checkup/state",
    }),
    "POST": frozenset({
        "api/core/capabilities", "api/ui_counters/_report", "internal/licensing/feature_usage/register",
        "api/content_management/rpc/get", "api/content_management/rpc/search", "api/content_management/rpc/mSearch",
    }),
}
PATTERN_IN_QUERY = frozenset({("GET", "internal/data_views/fields"), ("POST", "internal/data_views/_fields_for_wildcard")})
SUGGESTIONS = re.compile(r"internal/kibana/suggestions/values/(?P<index>[a-z0-9*-]+)")
SEARCH = re.compile(r"internal/search/ese(?:/(?P<id>[A-Za-z0-9_=-]+))?")
QUERY_PAIR = re.compile(r"(?P<name>[A-Za-z_]+)=(?P<value>[^&]*)")
REACHES_PAST_THE_INDEX = frozenset({"index", "_index", "indices", "namespace", "namespaces"})
FORWARDED_HEADERS = frozenset({"content-type", "accept", "elastic-api-version"})
FORWARDED_PREFIXES = ("kbn-", "x-elastic-", "x-kbn-")
ANSWER_HEADERS = ("Content-Type", "elastic-api-version", "kbn-license-sig", "kbn-name", "Cache-Control")
GATE_TIMEOUT = 120


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
        headers={"kbn-xsrf": "cr", "Content-Type": f"multipart/form-data; boundary={boundary}"},
    )


def status_request(base):
    return urllib.request.Request(f"{base.rstrip('/')}/api/status")


def settings_request(base, changes=None):
    return urllib.request.Request(
        f"{base.rstrip('/')}/api/kibana/settings",
        data=json.dumps({"changes": changes or SETTINGS}).encode(), method="POST",
        headers={"kbn-xsrf": "cr", "Content-Type": "application/json"},
    )


def space_request(base, space, create):
    path = "/api/spaces/space" if create else f"/api/spaces/space/{space}"
    body = {"id": space, "name": SPACE_NAME, "disabledFeatures": list(SPACE_FEATURES_OFF)}
    return urllib.request.Request(
        f"{base.rstrip('/')}{path}", data=json.dumps(body).encode(), method="POST" if create else "PUT",
        headers={"kbn-xsrf": "cr", "Content-Type": "application/json"},
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


def rison_key(name):
    return name if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) else rison(name)


def grid_state():
    return ",".join(f"{rison_key(name)}:(width:{width})" for name, width in COLUMN_WIDTHS.items())


def discover_path(view, start, end, kql="", columns=SESSION_COLUMNS):
    until = rison(end.isoformat()) if end else "now"
    global_state = f"(time:(from:{rison(start.isoformat())},to:{until}))"
    app_state = (
        f"(columns:!({','.join(columns)}),"
        f"dataSource:(dataViewId:{rison(view)},type:dataView),"
        "filters:!(),"
        f"grid:(columns:({grid_state()})),"
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
    return SPACE_PREFIX + re.sub(r"[^a-z0-9]+", "-", pattern.lower()).strip("-")


def _value(field):
    return f"(doc.containsKey('{field}') && doc['{field}'].size() > 0 ? String.valueOf(doc['{field}'].value) : '')"


def _literal(text):
    return json.dumps(text)


def log_source_script():
    return f"String module = {_value('event.module')}; if (module != '') {{ emit(module); }}"


def sensor_script(waf):
    return (
        f"String module = {_value('event.module')}; "
        f"if (module == 'modsecurity' || module == 'nginx') {{ emit({_literal(waf)}); }} "
        f"else if (module == 'suricata') {{ String leg = {_value('in_iface')}; if (leg != '') {{ emit(leg); }} }}"
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
        "else if (params['_source']['xff'] != null && shown.containsKey('x-forwarded-for')) { "
        "emit((String) shown.get('x-forwarded-for'), String.valueOf(params['_source']['xff'])); } "
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


def session_view(pattern, waf, runtime):
    fields = dict(runtime) | {
        "rule": {"type": "keyword", "script": {"source": rule_script()}},
        "rule_id": {"type": "keyword", "script": {"source": rule_id_script()}},
        "log_source": {"type": "keyword", "script": {"source": log_source_script()}},
        "sensor": {"type": "keyword", "script": {"source": sensor_script(waf)}},
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


def session_search(view):
    return {
        "type": "search",
        "id": SESSION_SEARCH,
        "attributes": {
            "title": SESSION_SEARCH_TITLE,
            "columns": list(SESSION_COLUMNS),
            "grid": {"columns": {name: {"width": width} for name, width in COLUMN_WIDTHS.items()}},
            "sort": [["@timestamp", "desc"]],
            "hideChart": False,
            "kibanaSavedObjectMeta": {"searchSourceJSON": json.dumps({
                "query": {"query": "", "language": "kuery"}, "filter": [],
                "indexRefName": "kibanaSavedObjectMeta.searchSourceJSON.index",
            })},
        },
        "references": [{"id": view["id"], "name": "kibanaSavedObjectMeta.searchSourceJSON.index",
                        "type": "index-pattern"}],
        "managed": False,
        "coreMigrationVersion": "8.8.0",
        "typeMigrationVersion": "10.4.0",
    }


def ensure_session_view(pattern, waf, send=None):
    try:
        with open(OBJECTS, "rb") as objects:
            view = session_view(pattern, waf, shared_runtime(objects.read()))
        send = send or send_json
        ensure_space(URL, view["id"], send)
        lines = "\n".join(json.dumps(found) for found in (view, session_search(view))).encode()
        imported = send(import_request(space_base(URL, view["id"]), lines))
        if not imported.get("success"):
            raise Refused(f"Kibana refused the data view for {pattern}: {imported.get('errors')}")
        send(settings_request(space_base(URL, view["id"]), SPACE_SETTINGS | {"defaultIndex": view["id"]}))
        return view["id"]
    except (Refused, OSError, ValueError, KeyError) as exc:
        print(f"kibana: no session data view for {pattern}: {exc}", flush=True)
        return None


def session_view_ready(pattern, waf, send=None, now=time.monotonic, again=False):
    made, at = VIEWS.get(pattern, (False, None))
    if again or not made and (at is None or now() - at >= VIEW_RETRY):
        made = ensure_session_view(pattern, waf, send) is not None
        VIEWS[pattern] = (made, now())
    return made


def _reaches_past_the_index(given):
    if isinstance(given, dict):
        named = REACHES_PAST_THE_INDEX & set(given)
        if named:
            return f"the request names {sorted(named)[0]!r}, which reads outside the session's indices"
        given = list(given.values())
    if isinstance(given, list):
        return next((found for found in map(_reaches_past_the_index, given) if found), None)
    return None


def _ours(index, pattern):
    return isinstance(index, str) and (pattern is None or index == pattern)


def _query_pairs(query):
    pairs = [QUERY_PAIR.fullmatch(part) for part in query.split("&") if part]
    return None if not all(pairs) else [(pair["name"], pair["value"]) for pair in pairs]


def _search_refusal(method, found, given, body, pattern):
    if method == "DELETE":
        return None if found["id"] and not body else "a search is cancelled by its id alone"
    params = given.get("params") if isinstance(given, dict) else None
    if not isinstance(params, dict) or not _ours(params.get("index"), pattern):
        return f"a search here reads {pattern or 'one index pattern'} alone"
    return _reaches_past_the_index([{key: value for key, value in given.items() if key != "params"},
                                    {key: value for key, value in params.items() if key != "index"}])


def refusal(method, uri, body, patterns):
    path, _, query = uri.partition("?")
    asked = GATED.fullmatch(path)
    if not asked:
        return f"{path} is not a call Discover makes"
    space, route = asked["space"], asked["route"]
    if patterns is not None and space not in patterns:
        return f"the space {space} is not the space of a session you have open"
    pattern = None if patterns is None else patterns[space]
    pairs = _query_pairs(query)
    if pairs is None or REACHES_PAST_THE_INDEX & {name for name, _ in pairs}:
        return "the query string names something outside the session's indices"
    try:
        given = json.loads(body) if body else None
    except ValueError:
        return "the body is not JSON"
    if (method, route) in PATTERN_IN_QUERY:
        named = [value for name, value in pairs if name == "pattern"]
        if len(named) != 1 or not _ours(named[0], pattern):
            return f"fields are listed for {pattern or 'one index pattern'} alone"
        return _reaches_past_the_index(given)
    found = SUGGESTIONS.fullmatch(route)
    if method == "POST" and found:
        if not _ours(found["index"], pattern):
            return f"values are suggested from {pattern} alone"
        return _reaches_past_the_index(given)
    found = SEARCH.fullmatch(route)
    if method in ("POST", "DELETE") and found:
        return _search_refusal(method, found, given, body, pattern)
    if route in DISCOVER_READS.get(method, ()):
        return _reaches_past_the_index(given)
    return f"{method} {route} is not a call Discover makes"


def forward(method, uri, headers, body, send=urllib.request.urlopen):
    origin = "{0.scheme}://{0.netloc}".format(urllib.parse.urlsplit(URL))
    sent = {name: value for name, value in headers.items()
            if name.lower() in FORWARDED_HEADERS or name.lower().startswith(FORWARDED_PREFIXES)}
    request = urllib.request.Request(origin + uri, data=body or None, method=method, headers=sent)
    try:
        answer = send(request, timeout=GATE_TIMEOUT)
    except urllib.error.HTTPError as exc:
        answer = exc
    with answer:
        kept = [(name, answer.headers[name]) for name in ANSWER_HEADERS if answer.headers.get(name)]
        return answer.getcode(), kept, answer.read()


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

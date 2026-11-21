import json
import re
from pathlib import Path

import yaml

from sandbox import kibana
from telemetry import elastic
from training.defence import ruletest

ROOT = Path(__file__).resolve().parents[2]
VHOSTS = ROOT / "deploy/waf/board.com.conf"
FILEBEAT = ROOT / "deploy/filebeat/filebeat.yml"
PIPELINE = ROOT / "deploy/elastic/ingest-pipeline.json"


def log_format() -> str:
    return re.search(r"log_format access escape=json '(\{.*\})';", VHOSTS.read_text())[1]


def refused_map() -> dict[str, str]:
    body = re.search(r"map \$status \$refused \{(.*?)\}", VHOSTS.read_text(), re.S)[1]
    return dict(re.findall(r"^\s*(\S+) (\S+);", body, re.M))


def marker_map() -> tuple[str, str, str]:
    body = re.search(r"map \$http_x_request_id \$logged_marker \{(.*?)\n\}", VHOSTS.read_text(), re.S)[1]
    [(pattern, value)] = re.findall(r'^\s*"~(.+)" (\S+);', body, re.M)
    [fallback] = re.findall(r'^\s*default (\S+);', body, re.M)
    return pattern, value, fallback


def logged_marker(given: str) -> bool:
    pattern, value, fallback = marker_map()
    assert (value, fallback) == ("$http_x_request_id", '""')
    return re.search(pattern, given) is not None


def logged(status: int, request_id: str = "", client: str = "5.188.10.10") -> dict:
    values = {"$time_iso8601": "2026-11-20T10:00:01+09:00", "$remote_addr": client, "$host": "board.com",
              "$request": "GET /posts/?q=1 HTTP/1.1", "$status": str(status),
              "$refused": refused_map().get(str(status), refused_map()["default"]),
              "$logged_marker": request_id if logged_marker(request_id) else ""}
    line = log_format()
    for name in sorted(values, key=len, reverse=True):
        line = line.replace(name, values[name])
    return json.loads(line)


def filebeat_access_steps() -> list[dict]:
    config = yaml.safe_load(FILEBEAT.read_text())
    [heard] = [each for each in config["filebeat.inputs"] if each.get("type") == "udp"]
    [steps] = [step["then"] for step in heard["processors"] if "if" in step
               and {"log.syslog.appname": "nginx-access"} in [each.get("equals") for each in step["if"]["and"]]]
    return steps


def collected(document: dict) -> dict:
    found = dict(document)
    for step in filebeat_access_steps():
        for moved in step.get("rename", {}).get("fields", []):
            if moved["from"] in found:
                value = found.pop(moved["from"])
                head, _, tail = moved["to"].partition(".")
                found.setdefault(head, {})[tail] = value
        for name, value in step.get("add_fields", {}).get("fields", {}).items():
            found[name] = value
    return found


def test_every_request_is_logged_not_only_the_refused_ones():
    text = VHOSTS.read_text()

    assert re.findall(r"^access_log (\S+) (\S+);$", text, re.M) == [("/var/log/nginx/access.json", "access")]
    assert " if=" not in text


def test_the_one_refused_map_names_the_statuses_the_platform_counts_as_refused():
    statuses = sorted(int(code) for code, flag in refused_map().items() if code != "default" and flag == "true")

    assert statuses == list(elastic.REFUSED_STATUSES) == list(ruletest.REFUSED_STATUSES) == [400, 403]
    assert refused_map()["default"] == "false"


def test_an_access_line_reaches_the_platform_as_one_access_event_with_its_marker():
    document = collected(logged(403, "action-9"))
    record = elastic.access_record("es1", document)

    assert document["event"] == {"module": elastic.ACCESS_MODULE}
    assert record["source_ip"] == "5.188.10.10" and record["status"] == 403 and record["refused"] is True
    assert record["marker"] == "action-9" and record["at"] is not None
    assert elastic.normalize("es1", document)[0]["marker"] == "action-9"


def test_only_a_marker_the_platform_could_have_made_is_logged_so_a_padded_header_cannot_break_the_line():
    made = ["0f3c" * 8, "1b4e28ba-2fa1-11d2-883f-0016d3cca427", "board-sqli-orderby-sqlmap"]
    forged = ["a1, a1", "x" * 129, "a1\x01", 'a1"}', "a1 a1", "\\" * 64]

    assert all(logged_marker(one) for one in made)
    assert not any(logged_marker(one) for one in forged), (
        "the learner sets X-Request-ID on kali; an access line past the shipper's 64 KiB loses its client_ip, "
        "and a request with no client_ip is charged to no origin")
    assert "$http_x_request_id" not in log_format()


def test_a_200_is_an_access_event_and_no_detection_and_an_unmarked_request_has_no_marker():
    document = collected(logged(200))

    assert elastic.access_record("es2", document)["marker"] is None
    assert elastic.access_record("es2", document)["refused"] is False
    assert elastic.normalize("es2", document) == []


def test_the_shipped_fields_stay_clear_of_the_template_s_object_fields():
    shipped = set(collected(logged(200)))

    assert not shipped & {"host", "log", "agent", "ecs", "process", "cloud"}, (
        "a top-level string under a name the template maps as an object fails the whole document")


def test_the_ingest_pipeline_dates_and_geolocates_an_access_record():
    processors = json.loads(PIPELINE.read_text())["processors"]
    dated = [step["date"] for step in processors if "date" in step and step["date"]["field"] == "time"]
    located = [step["geoip"] for step in processors if "geoip" in step and step["geoip"]["field"] == "client_ip"]

    assert dated and elastic.ACCESS_MODULE in dated[0]["if"] and dated[0]["target_field"] == "@timestamp"
    assert located and located[0]["target_field"] == "src_geo" and located[0]["ignore_missing"] is True


def test_the_kibana_alert_search_shows_refused_access_records_only():
    assert '(event.module : "nginx_access" and refused : true)' in kibana.ALERTS_QUERY
    saved = (ROOT / "deploy/kibana/objects.ndjson").read_text()

    assert saved.count("nginx_access") == 4
    assert re.search(r"event\.module : \W*nginx\W", saved) is None

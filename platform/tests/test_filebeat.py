import pathlib

import pytest

import yaml

from range import networks

FILEBEAT = pathlib.Path(__file__).resolve().parents[2] / "deploy/filebeat/filebeat.yml"


def flattened(settings, prefix=""):
    flat = {}
    for key, value in settings.items():
        path = f"{prefix}{key}"
        if isinstance(value, dict) and value:
            flat.update(flattened(value, f"{path}."))
        else:
            flat[path] = value
    return flat


def syslog_inputs():
    config = yaml.safe_load(FILEBEAT.read_text())
    return [each for each in config["filebeat.inputs"] if each.get("type") == "udp"]

def test_the_range_vms_ship_by_syslog_to_one_udp_input_on_the_collector_port():
    [heard] = syslog_inputs()

    assert heard["host"] == f"0.0.0.0:{networks.COLLECTOR_PORT}"
    assert next(iter(heard["processors"][0])) == "syslog"

def test_suricata_and_modsecurity_lines_are_decoded_into_the_documents_ingest_reads():
    [heard] = syslog_inputs()
    decoded = {}
    for step in heard["processors"]:
        if "if" not in step:
            continue
        appname = next(c["equals"]["log.syslog.appname"] for c in step["if"]["and"] if "equals" in c)
        names = [next(iter(each)) for each in step["then"]]
        tagged = next(each["add_fields"]["fields"]["event"]["module"] for each in step["then"] if "add_fields" in each)
        assert "decode_json_fields" in names
        decoded[appname] = tagged

    assert decoded == {"suricata": "suricata", "modsecurity": "modsecurity", "nginx": "nginx"}, (
        "ingest normalizes a document by event.module"
    )


def test_a_syslog_line_from_another_program_is_dropped_so_the_index_holds_only_the_engines_events():
    [heard] = syslog_inputs()

    assert heard["processors"][-1] == {"drop_event": {"when": {"not": {"has_fields": ["event.module"]}}}}, (
        "the learner's Discover shows every document of the index; the hosts' own system log lines are no events"
    )
    assert "cr_source" not in yaml.safe_dump(heard["processors"])


def test_the_data_stream_filebeat_makes_for_its_template_matches_the_template_s_pattern():
    from fnmatch import fnmatch

    config = yaml.safe_load(FILEBEAT.read_text())

    assert fnmatch(config["setup.template.name"], config["setup.template.pattern"]), (
        "Filebeat creates a data stream named after its template when it loads the template; on a fresh "
        "Elasticsearch a name outside the pattern failed the first connection with 'no matching index template'"
    )
    assert fnmatch("logs-1-2026.10.17", config["setup.template.pattern"])

def test_the_template_geolocates_every_document_by_default_not_only_when_filebeat_asks():
    config = yaml.safe_load(FILEBEAT.read_text())

    assert config["setup.template.settings"]["index.default_pipeline"] == "geoip", (
        "a per-request output pipeline was observed to not reach the data "
        "stream on one deployment; the template's default pipeline geolocates "
        "every write regardless, which is where src_ip -> country has to happen"
    )


def test_a_small_batch_of_events_is_published_within_a_second():
    config = flattened(yaml.safe_load(FILEBEAT.read_text()))

    assert config["queue.mem.flush.timeout"] == "1s", (
        "the memory queue holds events until 1600 have gathered or 10s pass, so "
        "the few alerts one attack case draws waited up to 10s to reach the index"
    )


def test_the_template_maps_the_ecs_and_beat_fields_alone_and_a_record_is_searchable_within_a_second():
    import re
    config = flattened(yaml.safe_load(FILEBEAT.read_text()))
    compose = yaml.safe_load((FILEBEAT.parents[2] / "compose.yaml").read_text())
    [script] = [part for part in compose["services"]["collector"]["entrypoint"] if "awk" in part]
    kept = set(re.search(r"\^\((.*?)\)\$", script)[1].split("|"))

    assert config["setup.template.fields"].endswith("/" + script.split("> ")[1].split()[0])
    assert config["setup.template.overwrite"] is True
    assert kept == {"ecs", "beat", "cloud", "docker", "host", "kubernetes", "process", "log"}, (
        "filebeat's whole fields.yml mapped 7,575 fields, every module's among them; Discover asks for every "
        "field of 500 rows and took 2.4 s for WAF records against 0.7 s with these groups alone, the same mapping "
        "for each of the 171 fields the documents carry"
    )
    assert config["setup.template.settings.index.refresh_interval"] == "1s"


def slot_rule():
    import re
    [heard] = syslog_inputs()
    [script] = [step["script"] for step in heard["processors"] if "script" in step]
    return re.compile(re.search(r"/(\^.*?)/\.exec", script["source"])[1])


@pytest.mark.parametrize("hostname, slot", [
    ("firewall.localdomain", "1"), ("cr-waf", "1"), ("cr-wargame-host", "1"),
    ("firewall-2.localdomain", "2"), ("cr-waf-2", "2"), ("cr-wargame-host-2", "2"),
])
def test_a_range_vm_s_syslog_is_tagged_with_the_slot_its_hostname_names(hostname, slot):
    found = slot_rule().match(hostname)

    assert (found[1] if found else "1") == slot


def test_a_slot_s_logs_go_to_that_slot_s_index_and_a_session_s_own_stack_to_its_own():
    config = yaml.safe_load(FILEBEAT.read_text())
    output = config["output.elasticsearch"]

    assert output["index"] == "logs-${CR_SESSION:shared}-sensors"
    assert output["indices"] == [{"index": "logs-%{[cr_slot]}-sensors",
                                  "when.has_fields": ["cr_slot"]}], (
        "two slots send from the same origin addresses at once; one index for both would "
        "score each session on the other's alerts"
    )


def test_a_document_does_not_carry_the_management_address_it_was_received_from():
    [heard] = syslog_inputs()
    [dropped] = [step["drop_fields"] for step in heard["processors"] if "drop_fields" in step]

    assert dropped["fields"] == ["log.source.address"] and dropped["ignore_missing"] is True


def test_a_refused_request_s_status_lands_where_the_ids_record_s_does_so_no_runtime_field_is_mapped_away():
    import json
    import re
    from defence import kibana
    root = FILEBEAT.parents[2]
    logged = re.search(r"log_format refused escape=json '(\{.*\})';", (root / "deploy/waf/board.com.conf").read_text())
    shipped = set(re.findall(r'"([A-Za-z_]+)":', logged[1]))
    [heard] = syslog_inputs()
    [nginx] = [step["then"] for step in heard["processors"] if "if" in step
               and {"log.syslog.appname": "nginx"} in [each.get("equals") for each in step["if"]["and"]]]
    for moved in (each for step in nginx for each in step.get("rename", {}).get("fields", [])):
        shipped = shipped - {moved["from"]} | {moved["to"]}
    runtime = json.loads(kibana.session_view("logs-1-sensors", "cr-waf", kibana.shared_runtime(
        (root / "deploy/kibana/objects.ndjson").read_bytes()))["attributes"]["runtimeFieldMap"])

    assert "http.status" in shipped and "doc['http.status']" in runtime["status"]["script"]["source"]
    assert not shipped & set(runtime), (
        "Kibana 8.15 leaves a runtime field out of runtime_mappings once an index maps a field of the same name; "
        "one refused record mapped a top-level status in slots 1 and 8, and status : 404 then matched no IDS row")

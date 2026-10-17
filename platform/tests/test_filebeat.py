import pathlib

import pytest

import yaml

from range import fabric

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


def filestream_inputs():
    config = yaml.safe_load(FILEBEAT.read_text())
    return [
        flattened(each) for each in config["filebeat.inputs"]
        if each.get("type") == "filestream"
    ]


def test_a_log_is_known_by_its_content_not_by_an_inode_the_vm_reassigns():
    inputs = filestream_inputs()
    by_inode = [
        each["id"] for each in inputs
        if each.get("prospector.scanner.fingerprint.enabled") is not True
        or sorted(k for k in each if k.startswith("file_identity."))
        != ["file_identity.fingerprint"]
    ]

    assert inputs and not by_inode, (
        f"{by_inode} identify their file by inode and device, and the logs are "
        f"bind mounts on colima's virtiofs, where inodes change across a VM "
        f"restart. Every restart made Filebeat read both logs again from "
        f"offset 0 and index hours-old events with a fresh @timestamp, inside "
        f"whatever session window was open"
    )


def syslog_inputs():
    config = yaml.safe_load(FILEBEAT.read_text())
    return [each for each in config["filebeat.inputs"] if each.get("type") == "udp"]

def test_the_range_vms_ship_by_syslog_to_one_udp_input_on_the_collector_port():
    [heard] = syslog_inputs()

    assert heard["host"] == f"0.0.0.0:{fabric.COLLECTOR_PORT}"
    assert next(iter(heard["processors"][0])) == "syslog"

def test_suricata_and_modsecurity_lines_are_decoded_into_the_documents_ingest_reads():
    [heard] = syslog_inputs()
    decoded = {}
    for step in heard["processors"]:
        if "if" not in step:
            continue
        appname = next(c["equals"]["log.syslog.appname"] for c in step["if"]["and"] if "equals" in c)
        names = [next(iter(each)) for each in step["then"]]
        tagged = next(each["add_fields"]["fields"]["fsl_source"] for each in step["then"] if "add_fields" in each)
        assert "decode_json_fields" in names
        decoded[appname] = tagged

    assert decoded == {"suricata": "suricata", "modsecurity": "modsecurity"}, (
        "ingest normalizes a document by fsl_source; a line from another "
        "program is kept as fsl_source syslog and scored as nothing"
    )


def test_the_data_stream_filebeat_makes_for_its_template_matches_the_template_s_pattern():
    from fnmatch import fnmatch

    config = yaml.safe_load(FILEBEAT.read_text())

    assert fnmatch(config["setup.template.name"], config["setup.template.pattern"]), (
        "Filebeat creates a data stream named after its template when it loads the template; on a fresh "
        "Elasticsearch a name outside the pattern failed the first connection with 'no matching index template'"
    )
    assert fnmatch("fsl-logs-slot1-2026.10.17", config["setup.template.pattern"])

def test_the_template_geolocates_every_document_by_default_not_only_when_filebeat_asks():
    config = yaml.safe_load(FILEBEAT.read_text())

    assert config["setup.template.settings"]["index.default_pipeline"] == "fsl-geoip", (
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


def slot_rule():
    import re
    [heard] = syslog_inputs()
    [script] = [step["script"] for step in heard["processors"] if "script" in step]
    return re.compile(re.search(r"/(\^.*?)/\.exec", script["source"])[1])


@pytest.mark.parametrize("hostname, slot", [
    ("fsl-edge.range.internal", "1"), ("fsl-waf", "1"), ("fsl-wargame-host", "1"),
    ("fsl-edge-2.range.internal", "2"), ("fsl-waf-2", "2"), ("fsl-wargame-host-2", "2"),
])
def test_a_range_vm_s_syslog_is_tagged_with_the_slot_its_hostname_names(hostname, slot):
    found = slot_rule().match(hostname)

    assert (found[1] if found else "1") == slot


def test_a_slot_s_logs_go_to_that_slot_s_index_and_a_session_s_own_stack_to_its_own():
    config = yaml.safe_load(FILEBEAT.read_text())
    output = config["output.elasticsearch"]

    assert output["index"] == "fsl-logs-${FSL_SESSION:shared}-%{+yyyy.MM.dd}"
    assert output["indices"] == [{"index": "fsl-logs-slot%{[fsl_slot]}-%{+yyyy.MM.dd}",
                                  "when.has_fields": ["fsl_slot"]}], (
        "two slots send from the same origin addresses at once; one index for both would "
        "score each session on the other's alerts"
    )

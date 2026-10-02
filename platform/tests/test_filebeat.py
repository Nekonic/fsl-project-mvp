import pathlib

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

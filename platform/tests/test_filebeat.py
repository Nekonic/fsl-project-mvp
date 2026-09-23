import pathlib

import yaml

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

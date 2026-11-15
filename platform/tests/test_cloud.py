import copy
import dataclasses

import pytest
import yaml

from range import cloud, openstack

DOCUMENT = yaml.safe_load(cloud.EXAMPLE.read_text())
RC = {
    "OS_AUTH_URL": "http://10.10.10.10:5000", "OS_USERNAME": "fsl-range", "OS_PASSWORD": "secret",
    "OS_PROJECT_NAME": "fsl-range", "OS_USER_DOMAIN_NAME": "Default", "OS_PROJECT_DOMAIN_NAME": "Default",
    "OS_REGION_NAME": "RegionOne", "OS_INTERFACE": "public",
}


def changed(**edits):
    document = copy.deepcopy(DOCUMENT)
    for dotted, value in edits.items():
        section, _, key = dotted.partition("__")
        if value is None:
            document[section].pop(key, None)
        else:
            document[section][key] = value
    return document


def refusal(document) -> str:
    with pytest.raises(cloud.Invalid) as raised:
        cloud.parse(document)
    return str(raised.value)


def test_a_password_in_the_file_is_refused_by_name_and_never_echoed():
    document = changed()
    document["identity"] = {"password": "hunter2"}
    said = refusal(document)

    assert "identity: not a section this file has" in said
    assert "hunter2" not in said


def test_the_identity_comes_from_the_sourced_rc_file_and_a_missing_variable_is_named():
    signed_in = cloud.identity({**RC, "OS_AUTH_URL": "http://10.10.10.10:5000/v3/"})

    assert signed_in.keystone == "http://10.10.10.10:5000"
    assert signed_in.user_domain == "Default" and signed_in.interface == "public"
    assert "secret" not in repr(signed_in), "an Identity printed in a traceback would show the password"
    with pytest.raises(cloud.Invalid, match="OS_PASSWORD, OS_REGION_NAME; source the project user's RC file"):
        cloud.identity({name: value for name, value in RC.items() if name not in ("OS_PASSWORD", "OS_REGION_NAME")})


@pytest.mark.parametrize("network, cidr, clash", [
    ("estate", "10.20.0.0/24", "overlaps estate 10.20.0.0/24"),
    ("mgmt", "172.17.5.0/24", "overlaps docker's default address pool 172.17.0.0/16"),
    ("estate", "172.29.4.0/24", "overlaps docker's default address pool 172.28.0.0/14"),
    ("platform", "192.168.50.0/24", "overlaps docker's default address pool 192.168.0.0/16"),
    ("mgmt", "172.31.0.0/24", "overlaps the compose network mgmt 172.31.0.0/24"),
], ids=["each-other", "docker-bridge", "docker-pool", "docker-pool-192", "compose-mgmt"])
def test_networks_that_overlap_each_other_docker_or_compose_are_refused(network, cidr, clash):
    assert clash in refusal(changed(**{f"network__{network}": cidr}))


def test_a_flavor_for_a_vm_the_range_no_longer_has_is_refused():
    assert "compute.flavors: names edge, which the range no longer has" in refusal(
        changed(compute__flavors={"platform": "m1.large", "range": "dba.range", "edge": "m1.medium"}))


def test_the_estate_is_wide_enough_for_a_slash_24_per_slot():
    assert "network.estate: must be a /16 or wider" in refusal(changed(network__estate="10.30.0.0/24"))


def test_the_settings_survive_the_trip_through_heat_and_the_environment():
    found = dataclasses.replace(cloud.parse(changed(compute__slots=2)), signed_in=cloud.identity(RC))

    carried = found.heat_parameters()

    assert openstack.pairs(carried["subnets"]) == found.inside
    assert carried["range_flavor"] == found.flavors["range"]
    assert carried["slots"] == "2"


def test_a_cloud_yaml_written_before_the_backups_section_still_parses_and_keeps_one_backup():
    document = copy.deepcopy(DOCUMENT)
    del document["backups"]

    assert cloud.parse(document).backups_keep == 1, (
        "every cloud.yaml in use predates backups.keep; refusing it would stop bin/cloud before anything runs"
    )

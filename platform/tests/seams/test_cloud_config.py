import copy
import dataclasses

import pytest
import yaml

from range import cloud_config as cloud, openstack

DOCUMENT = yaml.safe_load(cloud.EXAMPLE.read_text())
ENTRY = {
    "auth": {"auth_url": "http://10.10.10.10:5000/v3/", "username": "fsl-range", "password": "secret",
             "project_name": "fsl-range", "user_domain_name": "Default", "project_domain_name": "Default"},
    "region_name": "RegionOne",
}
FLAVORS = [
    {"name": "m1.small", "ram": 2048, "vcpus": 1, "disk": 20},
    {"name": "m1.xlarge", "ram": 16384, "vcpus": 8, "disk": 160},
    {"name": "m1.large", "ram": 8192, "vcpus": 4, "disk": 80},
    {"name": "dba.platform", "ram": 8192, "vcpus": 2, "disk": 40},
    {"name": "dba.range", "ram": 16384, "vcpus": 6, "disk": 60},
]


def written_clouds(tmp_path, **clouds):
    path = tmp_path / "clouds.yaml"
    path.write_text(yaml.safe_dump({"clouds": clouds}))
    return path


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


def test_the_identity_comes_from_the_clouds_yaml_entry_and_never_shows_its_password(tmp_path):
    signed_in = cloud.signed_in("fsl-range", written_clouds(tmp_path, **{"fsl-range": ENTRY}))

    assert signed_in.keystone == "http://10.10.10.10:5000"
    assert signed_in.user_domain == "Default" and signed_in.interface == "public"
    assert signed_in.cli_environment() == {"OS_CLOUD": "fsl-range", "OS_CLIENT_CONFIG_FILE": str(tmp_path / "clouds.yaml")}
    assert "secret" not in repr(signed_in), "an Identity printed in a traceback would show the password"


def test_a_missing_clouds_yaml_entry_stops_before_any_change_and_names_init(tmp_path):
    with pytest.raises(cloud.Invalid, match="has no entry fsl-range, so nothing was changed; run bin/cloud init"):
        cloud.signed_in("fsl-range", written_clouds(tmp_path, other=ENTRY))
    with pytest.raises(cloud.Invalid, match="has no entry fsl-range"):
        cloud.signed_in("fsl-range", tmp_path / "absent.yaml")


def test_the_entry_is_merged_into_clouds_yaml_without_touching_the_others_and_kept_private(tmp_path):
    path = written_clouds(tmp_path, **{"kolla-admin": {"auth": {"password": "admin-secret"}}, "fsl-range": {"old": 1}})

    cloud.write_clouds(path, "fsl-range", ENTRY)

    held = yaml.safe_load(path.read_text())["clouds"]
    assert held == {"kolla-admin": {"auth": {"password": "admin-secret"}}, "fsl-range": ENTRY}
    assert path.stat().st_mode & 0o777 == 0o600


def test_the_one_external_network_is_found_and_none_or_two_stop_init_with_the_list():
    networks = [{"name": "provider", "external": True}, {"name": "demo-net", "external": False}]

    assert cloud.external_network(networks) == "provider"
    with pytest.raises(cloud.Invalid, match="no external network .* the networks are: demo-net"):
        cloud.external_network(networks[1:])
    two = [*networks, {"name": "public", "external": True}]
    with pytest.raises(cloud.Invalid, match="more than one external network .*: provider, public"):
        cloud.external_network(two)
    assert cloud.external_network(two, "public") == "public", "a network cloud.yaml already names is kept"


def test_the_smallest_fitting_flavor_is_chosen_and_none_fitting_stops_init():
    assert cloud.fitting_flavor(FLAVORS, "platform")["name"] == "dba.platform"
    assert cloud.fitting_flavor(FLAVORS, "platform", "m1.large")["name"] == "m1.large", "a fitting choice is kept"
    assert cloud.fitting_flavor(FLAVORS, "platform", "m1.small")["name"] == "dba.platform"
    with pytest.raises(cloud.Invalid, match="no flavor fits the platform VM, which needs RAM 8192 MB, 2 vCPU"):
        cloud.fitting_flavor(FLAVORS[:1], "platform")


def test_the_quota_holds_the_platform_and_every_slot_s_four_vms_or_init_says_what_is_short():
    small = {"name": "dba.small", "ram": 2048, "vcpus": 1, "disk": 20}
    roles = {role: small for role in cloud.ROLES}
    limits = {"instances": 17, "cores": 24, "ram": 57344, "floating_ips": 1}

    assert cloud.quota_shortfall(limits, FLAVORS[2], roles, 4) == []
    assert cloud.quota_shortfall(limits, FLAVORS[2], roles, 5) == [
        "instances: the quota is 17, the platform and 5 slots of 4 VMs need 21"]


def test_init_sets_only_its_own_keys_in_cloud_yaml_and_keeps_the_comments():
    text = cloud.EXAMPLE.read_text().replace("cloud: fsl-range", "").replace("    board: 3", "    board: 2")

    written = cloud.with_settings(text, {("cloud",): "fsl-range", ("network", "external"): "public",
                                         ("compute", "flavors", "platform"): "m1.xlarge"})

    document = yaml.safe_load(written)
    assert document["cloud"] == "fsl-range" and document["network"]["external"] == "public"
    assert document["compute"]["flavors"] == {"platform": "m1.xlarge", **{role: "dba.small" for role in cloud.ROLES}}
    assert document["compute"]["pool"] == {"board": 2, "corp": 1}
    assert "public                      # the external network floating IPs come from" in written
    assert cloud.with_settings(written, {("network", "external"): "public"}) == written


@pytest.mark.parametrize("network, cidr, clash", [
    ("mgmt", "10.20.0.0/24", "overlaps mgmt 10.20.0.0/24"),
    ("mgmt", "172.17.5.0/24", "overlaps docker's default address pool 172.17.0.0/16"),
    ("mgmt", "172.29.4.0/24", "overlaps docker's default address pool 172.28.0.0/14"),
    ("platform", "192.168.50.0/24", "overlaps docker's default address pool 192.168.0.0/16"),
    ("mgmt", "172.31.0.0/24", "overlaps the compose network mgmt 172.31.0.0/24"),
], ids=["each-other", "docker-bridge", "docker-pool", "docker-pool-192", "compose-mgmt"])
def test_networks_that_overlap_each_other_docker_or_compose_are_refused(network, cidr, clash):
    assert clash in refusal(changed(**{f"network__{network}": cidr}))


def test_a_flavor_or_image_for_a_role_no_slot_has_is_refused():
    assert "compute.flavors: names edge, which is none of platform, kali, waf, infra, target" in refusal(
        changed(compute__flavors={"platform": "m1.large", "edge": "m1.medium"}))
    assert "compute.images: names platform, which is none of kali, waf, infra, target" in refusal(
        changed(compute__images={"platform": "ubuntu-24.04"}))
    assert "compute.pool: holds no slot" in refusal(changed(compute__pool={"board": 0, "corp": 0}))


def test_a_cloud_yaml_of_the_range_host_still_parses_and_gets_the_default_pool_images_and_flavors():
    older = changed(compute__pool=None, compute__images=None, compute__flavors={"platform": "m1.large", "range": "dba.range"},
                    compute__slots=8)
    older["network"].update(estate="10.30.0.0/16", mtu=1442)

    found = cloud.parse(older)

    assert found.pool == {"board": 3, "corp": 1} and found.slots == 4
    assert found.flavors == {"platform": "m1.large", **{role: "dba.small" for role in cloud.ROLES}}
    assert found.images == {role: f"cr-{role}-bake1" for role in cloud.ROLES}


def test_the_settings_survive_the_trip_through_heat_and_the_environment(tmp_path):
    found = dataclasses.replace(cloud.parse(changed(compute__pool={"board": 2, "corp": 1})),
                                signed_in=cloud.signed_in("fsl-range", written_clouds(tmp_path, **{"fsl-range": ENTRY})))

    carried = found.heat_parameters()

    assert openstack.pairs(carried["subnets"]) == found.inside == {"mgmt": "10.31.0.0/24"}
    assert openstack.pairs(carried["pool"]) == {"board": "2", "corp": "1"}
    assert openstack.pairs(carried["images"]) == {role: f"cr-{role}-bake1" for role in cloud.ROLES}
    assert openstack.pairs(carried["flavors"]) == {role: "dba.small" for role in cloud.ROLES}, (
        "the platform's own flavor is the stack's, not a slot role's")


def test_a_cloud_yaml_written_before_the_backups_section_still_parses_and_keeps_one_backup():
    document = copy.deepcopy(DOCUMENT)
    del document["backups"]

    assert cloud.parse(document).backups_keep == 1, (
        "every cloud.yaml in use predates backups.keep; refusing it would stop bin/cloud before anything runs"
    )


def test_the_platform_takes_ssh_and_its_ports_from_the_allowed_networks_open_to_all_unless_narrowed(tmp_path):
    entry = cloud.signed_in("fsl-range", written_clouds(tmp_path, **{"fsl-range": ENTRY}))
    older = copy.deepcopy(DOCUMENT)
    del older["network"]["allowed"]

    assert DOCUMENT["network"]["allowed"] == ["0.0.0.0/0"]
    assert dataclasses.replace(cloud.parse(older), signed_in=entry).heat_parameters()["allowed"] == "0.0.0.0/0"
    narrowed = cloud.parse(changed(network__allowed=["203.0.113.0/24", "198.51.100.7/32"]))
    assert dataclasses.replace(narrowed, signed_in=entry).heat_parameters()["allowed"] == (
        "203.0.113.0/24,198.51.100.7/32"
    )


@pytest.mark.parametrize("allowed", [[], "0.0.0.0/0", ["203.0.113.1/24"], ["not-a-network"], ["::/0"]])
def test_an_allowed_list_that_is_not_ipv4_networks_is_refused(allowed):
    assert "network.allowed" in refusal(changed(network__allowed=allowed))


def test_the_wargame_tag_the_target_image_was_baked_at_is_explicit_and_reaches_the_platform(tmp_path):
    entry = cloud.signed_in("fsl-range", written_clouds(tmp_path, **{"fsl-range": ENTRY}))

    assert DOCUMENT["compute"]["target_tag"] == cloud.TARGET_TAG
    older = dataclasses.replace(cloud.parse(changed(compute__target_tag=None)), signed_in=entry)
    assert older.heat_parameters()["target_tag"] == cloud.TARGET_TAG
    assert "compute.target_tag: must be the full commit" in refusal(changed(compute__target_tag="cf8d735e"))

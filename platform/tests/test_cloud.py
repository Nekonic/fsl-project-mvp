import copy
import subprocess

import pytest
import yaml

from range import cloud

DOCUMENT = yaml.safe_load(cloud.EXAMPLE.read_text())


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


def test_the_committed_example_is_a_usable_cloud():
    found = cloud.read(cloud.EXAMPLE)

    assert found.base_image == "ubuntu-24.04"
    assert found.inside == {"estate": "10.30.0.0/24", "mgmt": "10.31.0.0/24"}
    assert found.flavors["platform"] == "m1.large"
    assert found.role_flavors == {"edge": "m1.medium", "wargames": "m1.medium"}
    assert found.opnsense.image == "fsl-opnsense-26.7"


def test_the_filled_in_copy_is_never_committed():
    ignored = subprocess.run(["git", "check-ignore", "-q", str(cloud.CONFIGURED)],
                             cwd=cloud.FOLDER)

    assert ignored.returncode == 0


def test_a_missing_file_says_which_example_to_copy(tmp_path):
    with pytest.raises(cloud.Invalid, match="cloud.example.yaml"):
        cloud.read(tmp_path / "cloud.yaml")


def test_a_password_in_the_file_is_refused_by_name():
    said = refusal(changed(identity__password="hunter2"))

    assert "identity.password: not a setting this section has" in said
    assert "hunter2" not in said


def test_exactly_one_place_to_read_the_password_from():
    assert "exactly one of password_file and password_env" in refusal(
        changed(identity__password_env="FSL_PASSWORD"))
    assert "exactly one of password_file and password_env" in refusal(
        changed(identity__password_file=None))


def test_every_complaint_is_reported_at_once_with_its_dotted_key():
    said = refusal(changed(identity__keystone="http://k:5000/v3", network__mtu="1450",
                           compute__flavor={"platform": "m1.large"}))

    assert "identity.keystone: is Keystone's base URL without /v3" in said
    assert "network.mtu: must be a whole number" in said
    assert "compute.flavor: not a setting this section has" in said


def test_a_section_that_is_missing_is_named():
    document = copy.deepcopy(DOCUMENT)
    del document["opnsense"]

    assert "opnsense: missing" in refusal(document)


def test_networks_that_overlap_each_other_or_dockers_bridge_are_refused():
    assert "platform 10.20.0.0/24 overlaps estate 10.20.0.0/24" in refusal(
        changed(network__estate="10.20.0.0/24"))
    assert "mgmt 172.17.5.0/24 overlaps docker's default address pool 172.17.0.0/16" in refusal(
        changed(network__mgmt="172.17.5.0/24"))
    assert "network.estate: must be a private IPv4 network" in refusal(
        changed(network__estate="5.188.10.0/24")), "origins are public, so none can clash"


def test_networks_docker_may_hand_a_session_estate_are_refused():
    assert "estate 172.29.4.0/24 overlaps docker's default address pool 172.28.0.0/14" in refusal(
        changed(network__estate="172.29.4.0/24"))
    assert "platform 192.168.50.0/24 overlaps docker's default address pool 192.168.0.0/16" in refusal(
        changed(network__platform="192.168.50.0/24"))


def test_a_network_the_platform_s_own_compose_file_uses_is_refused():
    assert "mgmt 172.31.0.0/24 overlaps the compose network mgmt 172.31.0.0/24" in refusal(
        changed(network__mgmt="172.31.0.0/24"))
    assert any("origin" in name for name in cloud.taken()), "the origins are checked too"


def test_an_unquoted_version_is_refused_because_yaml_reads_it_as_a_number():
    document = changed()
    document["opnsense"]["version"] = 26.7

    assert "opnsense.version" in refusal(document)


def test_the_image_digest_and_key_fingerprint_must_be_sha256():
    said = refusal(changed(opnsense__image_sha256="abc", opnsense__pubkey_sha256="X" * 64))

    assert "opnsense.image_sha256: must be 64 lower-case hex digits" in said
    assert "opnsense.pubkey_sha256: must be 64 lower-case hex digits" in said


def test_the_platform_builder_and_range_flavors_are_required():
    assert "compute.flavors: lacks builder" in refusal(
        changed(compute__flavors={"platform": "m1.large", "range": "m1.small", "edge": "m1.medium"}))


def test_the_edge_flavor_is_required_because_the_opnsense_image_wants_3_gb():
    from range import opnsense

    assert opnsense.IMAGE_PROPERTIES["min_ram"] == 3072
    assert "compute.flavors: lacks edge" in refusal(
        changed(compute__flavors={"platform": "m1.large", "builder": "m1.medium", "range": "m1.small"}))


def test_the_password_is_read_from_the_named_variable(tmp_path):
    found = cloud.parse(changed(identity__password_file=None, identity__password_env="FSL_PW"))

    assert found.password({"FSL_PW": "secret"}) == "secret"
    with pytest.raises(cloud.Invalid, match="FSL_PW, which is unset"):
        found.password({})


def test_the_password_file_is_read_and_stripped(tmp_path):
    written = tmp_path / "password"
    written.write_text("secret\n")

    assert cloud.parse(changed(identity__password_file=str(written))).password({}) == "secret"


def test_the_opnsense_settings_survive_the_trip_through_heat_and_the_environment():
    found = cloud.read(cloud.EXAMPLE)

    carried = cloud.opnsense_from(found.heat_parameters()["opnsense"])

    assert carried == found.opnsense
    assert cloud.pairs(found.heat_parameters()["subnets"]) == found.inside
    assert cloud.pairs(found.heat_parameters()["role_flavors"]) == found.role_flavors


def test_a_pair_that_is_not_key_value_is_refused():
    with pytest.raises(cloud.Invalid, match="'estate' is not key=value"):
        cloud.pairs("estate mgmt=10.31.0.0/24")


def test_the_platform_refuses_a_cloud_setting_it_cannot_parse():
    from range import declared, openstack
    from range.ports import RangeUnavailable

    with pytest.raises(RangeUnavailable, match="FSL_OPENSTACK_SUBNETS"):
        openstack.connect(declared.read(), keystone="http://k:5000", user="u", password="p",
                          project="p", ssh_user="ubuntu", ssh_key="/k", region="R",
                          interface="public", domain="default", subnets="estate")


def test_the_floating_ip_to_keep_is_optional_and_must_be_an_address():
    assert cloud.parse(changed(network__address="192.168.0.210")).address == "192.168.0.210"
    assert cloud.parse(changed(network__address="")).address == ""
    assert "network.address: must be the IPv4 address" in refusal(changed(network__address="fip-one"))

from range import declared, fabric, pfsense

OS = declared.read(flavor="openstack")

def test_home_net_holds_every_origin_subnet_and_the_inside_networks():
    home = pfsense.home_net(OS)

    assert home.startswith("[") and home.endswith("]")
    members = home[1:-1].split(",")
    for origin in OS.origins:
        assert origin.subnet in members, origin.id
    assert fabric.INSIDE["estate"] in members
    assert fabric.INSIDE[fabric.MANAGEMENT] in members

def test_home_net_counts_the_origins_so_the_attacker_side_is_not_external():
    members = pfsense.home_net(OS)[1:-1].split(",")

    assert len([m for m in members if m in {o.subnet for o in OS.origins}]) == 30, (
        "the edge sensor watches traffic whose source is an origin subnet; if "
        "those were external, a rule reading EXTERNAL_NET->HOME_NET would still "
        "match, but the home side has to name where the defended hosts are"
    )
    assert members[-2:] == [fabric.INSIDE["estate"], fabric.INSIDE[fabric.MANAGEMENT]]

def test_home_net_is_one_line_with_no_spaces_for_a_suricata_variable():
    assert " " not in pfsense.home_net(OS)

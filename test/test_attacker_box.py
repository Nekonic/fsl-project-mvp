def test_the_origin_the_attack_state_names_is_an_address_of_the_box(terminal_round):
    origin = terminal_round["origin"]

    assert origin and origin["ip"] in terminal_round["box_addresses"], (
        f"the attack state says the box leaves from {origin}, but the box's own addresses are "
        f"{terminal_round['box_addresses']}; every charge and every window would name an address nothing sends from"
    )


def test_moving_to_the_next_origin_moves_the_shell_s_source(terminal_round):
    elsewhere = terminal_round["elsewhere"]
    assert elsewhere, "the round offers only one origin"
    token, alerts = terminal_round["moved"]
    assert alerts, f"nothing alerted on the probe {token}"

    sources = {alert["src_ip"] for alert in alerts}

    assert elsewhere["ip"] in sources, (
        f"moved the box to {elsewhere['label']} ({elsewhere['ip']}) and the alerts came from {sorted(sources)}"
    )

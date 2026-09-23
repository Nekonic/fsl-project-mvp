import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
RULES = ROOT / "deploy/suricata/rules/local.rules"
SENSOR = ROOT / "deploy/suricata/suricata.yaml"

def live_rules():
    return [
        line for line in RULES.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]

def test_no_experiment_is_left_behind_in_the_shipped_rule_set():
    sids = sorted(
        int(m.group(1))
        for line in live_rules()
        for m in [re.search(r"sid:(\d+)", line)] if m
    )
    scratch = [sid for sid in sids if sid >= 9009000]

    assert scratch == [], (
        f"{scratch} are in the range this repo uses for throwaway rules in "
        f"tests and hand experiments, and they are in the file the stack "
        f"ships. A rule left behind here changes every score after it"
    )

def test_every_shipped_rule_has_a_distinct_sid():
    sids = [
        re.search(r"sid:(\d+)", line).group(1)
        for line in live_rules() if re.search(r"sid:(\d+)", line)
    ]

    assert len(sids) == len(set(sids)), f"duplicate sids: {sids}"

def test_the_port_variable_names_ports_the_sensor_can_observe():
    import yaml

    ports = str(yaml.safe_load(SENSOR.read_text())["vars"]["port-groups"]["HTTP_PORTS"])

    assert "8080" not in ports, (
        "8080 is the host-published port. Docker translates it before the "
        "packet reaches any interface the sensor taps, so a rule written "
        "$HOME_NET $HTTP_PORTS matched nothing: measured 0 alerts against 4 "
        "from the identical rule using any"
    )
    assert "80" in ports and "3000" in ports, ports


def test_the_sensor_ties_an_alert_to_its_transaction_when_it_can():
    import yaml

    config = yaml.safe_load((pathlib.Path(__file__).resolve().parents[2] / "deploy/suricata/suricata.yaml").read_text())

    assert (config.get("detect") or {}).get("guess-applayer-tx") is True, (
        "a rule written without an app-layer buffer alerts with no tx_id, the "
        "marker join is keyed on (flow_id, tx_id), and the case it caught scored "
        "a miss; Suricata guesses the transaction only when told to"
    )

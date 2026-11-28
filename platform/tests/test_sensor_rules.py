import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
RULES = ROOT / "deploy/suricata/rules/board.rules"
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
    assert len(sids) == len(set(sids)), f"duplicate sids: {sids}"

def test_the_shipped_rule_file_explains_itself_in_korean_and_disables_rules_by_commenting_them_out():
    prose = [line for line in RULES.read_text().splitlines()
             if line.startswith("#") and not re.match(r"#\s*(alert|drop|pass|reject)\s", line)]

    assert prose and [line for line in prose if not re.search("[가-힣]", line)] == []

def test_the_port_variable_names_every_port_the_waf_proxies_to():
    import yaml

    ports = str(yaml.safe_load(SENSOR.read_text())["vars"]["port-groups"]["HTTP_PORTS"])
    declared = {int(port) for port in re.findall(r"\d+", ports)}
    waf = (ROOT / "deploy/roles/waf/sites.conf").read_text()
    upstream = {int(port) for port in re.findall(r"proxy_pass\s+http://[\w.-]+:(\d+)", waf)}

    assert upstream, "sites.conf names no upstream port"
    assert upstream <= declared, (
        f"the WAF proxies to {sorted(upstream)} but HTTP_PORTS is {ports}; a rule "
        f"written $HOME_NET $HTTP_PORTS would miss the traffic on the ports left out"
    )


def test_the_sensor_ties_an_alert_to_its_transaction_when_it_can():
    import yaml

    config = yaml.safe_load((pathlib.Path(__file__).resolve().parents[2] / "deploy/suricata/suricata.yaml").read_text())

    assert (config.get("detect") or {}).get("guess-applayer-tx") is True, (
        "a rule written without an app-layer buffer alerts with no tx_id, the "
        "marker join is keyed on (flow_id, tx_id), and the case it caught scored "
        "a miss; Suricata guesses the transaction only when told to"
    )

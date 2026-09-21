import ipaddress
import json
import subprocess
import time
import uuid

import pytest
import requests

from conftest import PLATFORM_URL

BOX = "fsl-kali"

                                                                         
                                                                            
                                             
TOOLS = [
    "nmap", "whatweb",                                
    "ffuf", "gobuster",                                
    "nikto", "sqlmap",                                        
    "hydra",                                                         
    "curl", "wget", "nc", "dig", "jq",                   
]

def in_box(*argv, timeout=60):
    return subprocess.run(
        ["docker", "exec", BOX, *argv],
        capture_output=True, text=True, timeout=timeout,
    )

@pytest.mark.parametrize("tool", TOOLS)
def test_the_box_has_the_tool(stack_is_up, tool):
    found = in_box("sh", "-c", f"command -v {tool}")

    assert found.returncode == 0, (
        f"{tool} is not on the attacker box, so nobody can use it there and a "
        f"case declaring it would fail at the prompt too"
    )

def test_a_directory_brute_force_has_a_wordlist_to_use(stack_is_up):
                                                                        
                                                                            
                                                                          
                                   
    found = in_box("sh", "-c", "wc -l < /usr/share/wordlists/dirb/common.txt")

    assert found.returncode == 0, "no directory wordlist on the box"
    assert int(found.stdout.strip()) > 100

def test_the_shell_is_told_what_to_attack(stack_is_up):
                                                                 
    target = in_box("sh", "-c", "echo $FSL_TARGET").stdout.strip()
    host = in_box("sh", "-c", "echo $FSL_TARGET_HOST").stdout.strip()

    assert target.startswith("http://"), target
    assert host and host in target

@pytest.fixture(scope="module")
def box(stack_is_up):
    return requests.get(f"{PLATFORM_URL}/api/attacker/", timeout=120).json()

def test_the_console_reports_both_addresses_the_box_can_leave_by(box):
                                                                             
                                                                             
                  
    assert box["source_ip"], box
    assert box["direct_ip"], box
    assert box["source_ip"] != box["direct_ip"], (
        "the proxied and direct addresses are the same, so one of them is "
        "wrong and every raw-TCP window would be attributed to the proxy"
    )

def test_the_direct_address_is_the_box_itself(box):
    mine = in_box("sh", "-c", "hostname -I").stdout.split()

    assert box["direct_ip"] in mine, (
        f"the console says raw TCP leaves from {box['direct_ip']}, but the "
        f"box's own addresses are {mine}"
    )

def test_the_proxied_address_is_not_the_box(box):
    mine = in_box("sh", "-c", "hostname -I").stdout.split()

    assert box["source_ip"] not in mine

                                                                            
                                                                          
                                                                           
                                                                        
                              

PUBLIC_HOST = "shop.com"

def test_the_shell_is_pointed_at_a_site_not_at_the_defence(stack_is_up):
    target = in_box("sh", "-c", "echo $FSL_TARGET").stdout.strip()

    assert PUBLIC_HOST in target, target
    assert "waf" not in target, (
        f"the shell is told to attack {target}, which names the defence. "
        f"An attacker would not know it is there."
    )

def test_the_console_shows_the_name_a_person_types(box):
    assert PUBLIC_HOST in box["public_url"], box["public_url"]

def _alerts_mentioning(token, lines=300):
    out = subprocess.run(
        ["docker", "exec", "fsl-suricata", "sh", "-c",
         f"tail -{lines} /var/log/suricata/eve.json"],
        capture_output=True, text=True, timeout=60,
    )
    found = []
    for line in out.stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("event_type") == "alert" and token in json.dumps(event.get("http", {})):
            found.append(event)
    return found

def _attack_from_the_shell(token):
    payload = f"/rest/products/search?q=%27%20OR%201%3D1--%20{token}"
    in_box("sh", "-c", f'curl -s -o /dev/null --max-time 20 "$FSL_TARGET{payload}"')
    time.sleep(5)
    alerts = _alerts_mentioning(token)
    assert alerts, f"nothing alerted on the probe {token}"
    return alerts

def test_what_the_attacker_typed_is_what_the_alert_records(stack_is_up):
    alerts = _attack_from_the_shell(f"zz{uuid.uuid4().hex[:8]}")
    hosts = {a["http"].get("hostname") for a in alerts}

    assert hosts == {PUBLIC_HOST}, (
        f"the site was attacked under {sorted(hosts)}; an alert naming a "
        f"routing host records a name nobody dialled"
    )

def test_choosing_an_origin_moves_the_source_without_renaming_the_site(stack_is_up, box):
    elsewhere = next(
        (o for o in requests.get(f"{PLATFORM_URL}/api/origins/", timeout=60).json()["origins"]
         if not o["default"]), None)
    assert elsewhere, "the stack offers only one origin"

    try:
        requests.post(f"{PLATFORM_URL}/api/attacker/origin/",
                      json={"origin": elsewhere["id"]}, timeout=60)
        alerts = _attack_from_the_shell(f"zz{uuid.uuid4().hex[:8]}")
    finally:
        requests.post(f"{PLATFORM_URL}/api/attacker/origin/",
                      json={"origin": ""}, timeout=60)

    subnet = ipaddress.ip_network(elsewhere["subnet"])
    sources = {a["src_ip"] for a in alerts}

    assert any(ipaddress.ip_address(ip) in subnet for ip in sources), (
        f"asked the shell to leave by {elsewhere['label']} ({subnet}) and the "
        f"alerts came from {sorted(sources)}"
    )
    assert {a["http"].get("hostname") for a in alerts} == {PUBLIC_HOST}

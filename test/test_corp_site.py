import re

from range import ATTACKER, run


def corp_page(path):
    fetched = run(ATTACKER, [
        "curl", "-s", "--max-time", "20", "-w", "\n%{http_code}",
        "-H", "Host: corp.com", f"http://board.com{path}",
    ])
    body, _, code = fetched.stdout.rpartition("\n")
    return code.strip(), body


def test_the_corp_site_serves_through_the_waf():
    code, body = corp_page("/")
    assert code == "200", body[:300]
    assert "Northwind Community" in body, body[:300]
    assert "wp-content" in body, body[:300]


def test_an_unrouted_host_is_the_board_not_the_corp_site():
    probe = run(ATTACKER, [
        "curl", "-s", "--max-time", "20", "-H", "Host: board.com", "http://board.com/",
    ])
    assert "Northwind Community" not in probe.stdout
    assert "wp-content" not in probe.stdout


def test_the_corp_registration_form_the_attack_targets_exists():
    code, body = corp_page("/register/")
    assert code == "200", body[:300]
    assert "um-form" in body, body[:300]
    assert re.search(r'name="user_login-\d+"', body), body[:300]
    assert 'name="um_request"' in body, body[:300]


def test_the_baseline_state_reads_over_the_corp_db_container():
    options = run("corp-db", [
        "mysql", "-N", "-uwordpress", "-pwordpress", "wordpress", "-e",
        "SELECT option_name,option_value FROM wp_options "
        "WHERE option_name IN ('users_can_register','default_role');",
    ]).stdout
    rows = dict(line.split("\t") for line in options.splitlines() if line.strip())
    assert rows.get("users_can_register") == "0"
    assert rows.get("default_role") == "subscriber"

    admins = run("corp-db", [
        "mysql", "-N", "-uwordpress", "-pwordpress", "wordpress", "-e",
        "SELECT user_id FROM wp_usermeta WHERE meta_key='wp_capabilities' "
        "AND meta_value LIKE '%administrator%';",
    ]).stdout
    assert len([x for x in admins.split() if x]) >= 1


def test_the_three_vulnerable_plugins_are_active():
    listed = run("corp", [
        "wp", "plugin", "list", "--status=active", "--field=name", "--allow-root",
    ]).stdout
    active = set(listed.split())
    assert {"ultimate-member", "wp-gdpr-compliance", "easy-post-submission"} <= active, active

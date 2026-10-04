from range import ATTACKER, run


def test_the_corp_site_serves_through_the_waf():
    probe = run(ATTACKER, [
        "curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "--max-time", "20",
        "-H", "Host: corp.com", "http://board.com/",
    ])
    assert probe.stdout.strip() == "200", probe.output


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

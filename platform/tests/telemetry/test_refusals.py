from datetime import datetime, timezone

from telemetry import waf_log

AT = datetime(2026, 11, 21, 1, 0, tzinfo=timezone.utc)
TAIL = 'server: board.com, request: "GET / HTTP/1.1", host: "board.com"'


def test_a_deny_rule_names_the_client_it_refused():
    line = f"2026/11/21 10:00:00 [error] 812#812: *41 access forbidden by rule, client: 5.188.10.10, {TAIL}"

    assert waf_log.refusal_in(line, AT) == waf_log.Refusal(at=AT, ip="5.188.10.10", by="deny")


def test_a_rate_limit_names_its_zone_and_client():
    line = (f'2026/11/21 10:00:00 [error] 812#812: *42 limiting requests, excess: 5.120 by zone "perip", '
            f"client: 2001:db8::7, {TAIL}")

    assert waf_log.refusal_in(line, AT) == waf_log.Refusal(at=AT, ip="2001:db8::7", by="limit_req", zone="perip")


def test_a_crs_refusal_a_delayed_request_and_a_dry_run_are_no_refusal():
    lines = [
        f"2026/11/21 10:00:00 [error] 812#812: *43 [client 5.188.10.10] ModSecurity: Access denied with code 403 "
        f'(phase 2). [id "949110"], client: 5.188.10.10, {TAIL}',
        f'2026/11/21 10:00:00 [warn] 812#812: *44 delaying request, excess: 0.500, by zone "perip", '
        f"client: 5.188.10.10, {TAIL}",
        f'2026/11/21 10:00:00 [error] 812#812: *45 limiting requests, dry run, excess: 5.120 by zone "perip", '
        f"client: 5.188.10.10, {TAIL}",
    ]

    assert [waf_log.refusal_in(line, AT) for line in lines] == [None, None, None]

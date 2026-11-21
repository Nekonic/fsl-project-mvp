from datetime import timedelta

import pytest

from telemetry import alerts as alert_feed
from telemetry.models import Event
from tests import rounds
from tests.training.defence.conftest import SEARCH_RULE
from training.defence import rules as service
from users.players import issue_token

BASE = "/api/rounds/{round}/defence/"
HTTP = "/etc/nginx/defence/http.conf"
ATTACKER = "198.51.100.9"
CUSTOMER = "203.0.113.50"


def url(found, tail):
    return BASE.format(round=found.pk) + tail


def suricata(at, marker="m1", ip=ATTACKER):
    return {"@timestamp": at, "event": {"module": "suricata"}, "event_type": "alert", "timestamp": at, "src_ip": ip,
            "alert": {"signature_id": 1001, "signature": "SQL injection in search"},
            "http": {"url": "/search/?q=x", "request_headers": [{"name": "X-Request-ID", "value": marker}]}}


def modsecurity(at, marker="m2", ip=ATTACKER):
    return {"@timestamp": at, "event": {"module": "modsecurity"},
            "transaction": {"time_stamp": at, "client_ip": ip,
                            "request": {"uri": "/accounts/login/", "headers": {"X-Request-ID": marker}},
                            "messages": [{"message": "SQL Injection Attack", "details": {"ruleId": "942100",
                                                                                        "severity": "2"}}]}}


def access(at, status, ip=ATTACKER, marker=None):
    return {"@timestamp": at, "time": at, "event": {"module": "nginx_access"}, "client_ip": ip, "status": status,
            "request": "GET /admin/ HTTP/1.1", **({"request_id": marker} if marker else {})}


def stamp(at, seconds=0):
    return (at + timedelta(seconds=seconds)).isoformat()


def test_ingest_stores_each_alert_once_with_its_engine_rule_and_marker(board_round, cyber_range, es, at):
    es.add("s1", suricata(stamp(at))).add("w1", modsecurity(stamp(at, 1))).add("a1", access(stamp(at, 2), 403))
    es.add("a2", access(stamp(at, 3), 200))

    first = alert_feed.ingest_alerts(board_round)
    again = alert_feed.ingest_alerts(board_round)

    assert [(row.engine, row.rule, row.marker, row.blocked) for row in first] == [
        ("ids", "1001", "m1", False), ("waf", "942100", "m2", False), ("waf", "403", None, True)]
    assert again == []
    assert [record.detection_id for record in alert_feed.detections(board_round)] == ["s1", "w1:0", "a1"]
    seen = Event.objects.filter(round_id=board_round.pk, kind="alert.seen")
    assert seen.count() == 3 and {event.player_side for event in seen} == {"defence"}


@pytest.mark.parametrize("first", ["alert", "http"])
def test_an_alert_and_its_transaction_s_http_record_read_apart_still_join_marker_and_client(board_round, cyber_range,
                                                                                          es, at, first):
    alert_at, record_at = (stamp(at), stamp(at, 1)) if first == "alert" else (stamp(at, 1), stamp(at))
    alert = {**suricata(alert_at, ip="10.30.0.247"), "flow_id": 7, "tx_id": 0, "http": {"url": "/search/?q=x"}}
    record = {"@timestamp": record_at, "event": {"module": "suricata"}, "event_type": "http", "flow_id": 7,
              "tx_id": 0, "src_ip": "10.30.0.247", "xff": ATTACKER,
              "http": {"request_headers": [{"name": "X-Request-ID", "value": "m7"}]}}
    reads = {"alert": ("s7", alert), "http": ("h7", record)}

    es.add(*reads[first])
    alert_feed.ingest_alerts(board_round)
    es.add(*reads["http" if first == "alert" else "alert"])
    alert_feed.ingest_alerts(board_round)

    [stored] = alert_feed.detections(board_round)
    assert (stored.marker, stored.src_ip) == ("m7", ATTACKER)


def test_alerts_page_by_detection_id_and_filter_by_engine_rule_and_source(as_defender, board_round, cyber_range, es,
                                                                         at):
    es.add("s1", suricata(stamp(at))).add("w1", modsecurity(stamp(at, 1), ip=CUSTOMER))
    alert_feed.ingest_alerts(board_round)

    every = as_defender.get(url(board_round, "alerts/")).json()
    waf = as_defender.get(url(board_round, "alerts/"), {"engine": "waf"}).json()
    by_rule = as_defender.get(url(board_round, "alerts/"), {"rule": "1001"}).json()
    by_source = as_defender.get(url(board_round, "alerts/"), {"src": CUSTOMER}).json()
    later = as_defender.get(url(board_round, "alerts/"), {"after": every["next"]}).json()

    assert [alert["engine"] for alert in every["alerts"]] == ["ids", "waf"]
    assert every["alerts"][0] | {"id": 0, "time": ""} == {
        "id": 0, "time": "", "engine": "ids", "rule": "1001", "signature": "SQL injection in search",
        "src_ip": ATTACKER, "request_id": "m1", "uri": "/search/?q=x", "blocked": False}
    assert [alert["rule"] for alert in waf["alerts"]] == ["942100"]
    assert [alert["engine"] for alert in by_rule["alerts"]] == ["ids"]
    assert [alert["src_ip"] for alert in by_source["alerts"]] == [CUSTOMER]
    assert later == {"alerts": [], "next": every["next"]}
    assert as_defender.get(url(board_round, "alerts/"), {"engine": "kql"}).status_code == 400


def test_traffic_counts_requests_and_refusals_by_origin_from_the_access_log(as_defender, board_round, cyber_range,
                                                                           es, at):
    es.add("a1", access(stamp(at), 200)).add("a2", access(stamp(at, 1), 403)).add("a3", access(stamp(at, 2), 200,
                                                                                               ip=CUSTOMER))
    es.add("s1", suricata(stamp(at, 3)))

    first = as_defender.get(url(board_round, "traffic/")).json()
    es.add("a4", access(stamp(at, 4), 400))
    second = as_defender.get(url(board_round, "traffic/"), {"after": first["next"]}).json()

    assert [(row["ip"], row["requests"], row["refused"]) for row in first["by_origin"]] == [
        (ATTACKER, 2, 1), (CUSTOMER, 1, 0)]
    assert [(row["ip"], row["requests"], row["refused"]) for row in second["by_origin"]] == [(ATTACKER, 1, 1)]
    assert as_defender.get(url(board_round, "traffic/"), {"after": "not-a-cursor"}).status_code == 400


def test_the_state_shows_the_brief_target_objectives_versions_and_alert_count(as_defender, board_round, cyber_range,
                                                                             es, at):
    es.add("s1", suricata(stamp(at)))
    alert_feed.ingest_alerts(board_round)
    as_defender.post(url(board_round, "ids/rules/apply/"), {"text": SEARCH_RULE, "base_version": 0}, format="json")

    shown = as_defender.get(url(board_round, "state/")).json()

    assert shown["round"] == board_round.pk and shown["phase"] == "running"
    assert shown["brief"]["title"] == "Placeholder round"
    assert shown["target"] == {"public_url": "http://board.com", "hosts": ["board.com"]}
    assert shown["objectives"] == [{"key": "board-auth-user-admin", "name": shown["objectives"][0]["name"],
                                    "state": "kept", "seen": False}]
    assert (shown["ids"], shown["waf"], shown["alerts_total"]) == ({"version": 1}, {"version": 0}, 1)


def test_an_attack_player_reaches_no_defence_route(browser, board_round, make_user):
    attacker = make_user("attacker")
    rounds.playing(board_round, "attack", user=attacker)
    browser.force_authenticate(attacker)

    answer = browser.get(url(board_round, "ids/rules/"))

    assert answer.status_code == 403
    assert answer.json() == {"errors": [{"path": "", "code": "not_a_player"}]}


def test_a_bot_defence_player_reaches_its_side_with_its_token(browser, board_round):
    player = rounds.playing(board_round, "defence", bot_name="defender-bot")
    token = issue_token(player)

    answer = browser.get(url(board_round, "probes/"), HTTP_AUTHORIZATION=f"Bearer {token}")
    test = browser.post(url(board_round, "ids/rules/test/"), {"text": SEARCH_RULE}, format="json",
                        HTTP_AUTHORIZATION=f"Bearer {token}")

    assert answer.status_code == 200
    assert test.status_code == 200 and test.json()["ok"] is True


def test_writes_after_the_round_ended_are_refused_and_reads_still_answer(as_defender, board_round):
    board_round.phase, board_round.ended = "ended", board_round.started + timedelta(minutes=5)
    board_round.save()

    write = as_defender.post(url(board_round, "ids/rules/apply/"), {"text": SEARCH_RULE, "base_version": 0},
                             format="json")

    assert write.status_code == 409
    assert write.json()["errors"][0]["code"] == "round_closed"
    assert as_defender.get(url(board_round, "probes/")).status_code == 200


def test_writes_before_the_round_started_are_refused(as_defender, board_round):
    board_round.phase = "created"
    board_round.save()

    answer = as_defender.post(url(board_round, "waf/check/"), {"files": {HTTP: "deny all;\n"}}, format="json")

    assert answer.status_code == 409
    assert answer.json()["errors"][0]["code"] == "round_not_started"


def test_the_round_start_posture_is_applied_to_both_engines(board_round, cyber_range):
    board_round.snapshot["round"]["posture"] = {"name": "start", "suricata_rules": SEARCH_RULE,
                                                "waf_files": {HTTP: "limit_req_zone $binary_remote_addr "
                                                                    "zone=ip:10m rate=5r/s;\n"}}
    board_round.save()

    service.apply_posture(board_round)

    assert cyber_range.sensors["sensor"].rules == SEARCH_RULE
    assert cyber_range.gateway.files[HTTP].startswith("limit_req_zone")
    assert [(one.version, one.source) for one in service.versions(board_round, "ids")] == [(1, "setup")]
    assert [(one.version, one.source) for one in service.versions(board_round, "waf")] == [(1, "setup")]


def test_a_start_posture_with_no_waf_files_records_the_live_files_as_the_first_version(board_round, cyber_range):
    board_round.snapshot["round"]["posture"] = {"name": "start", "suricata_rules": "", "waf_files": {}}
    board_round.save()
    cyber_range.gateway.files[HTTP] = "deny 192.0.2.1;\n"

    service.apply_posture(board_round)

    [first] = service.versions(board_round, "waf")
    assert (first.version, first.source, first.files[HTTP]) == (1, "setup", "deny 192.0.2.1;\n")
    assert cyber_range.gateway.workers == 1, "recording what runs reloads nothing"

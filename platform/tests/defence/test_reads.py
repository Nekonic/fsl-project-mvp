from datetime import timedelta

from defence import service
from events.models import Event
from match.auth import issue_token
from tests import rounds
from tests.defence.conftest import SEARCH_RULE

BASE = "/api/rounds/{round}/defence/"
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

    first = service.ingest_alerts(board_round)
    again = service.ingest_alerts(board_round)

    assert [(row.engine, row.rule, row.marker, row.blocked) for row in first] == [
        ("ids", "1001", "m1", False), ("waf", "942100", "m2", False), ("waf", "403", None, True)]
    assert again == []
    assert [record.detection_id for record in service.detections(board_round)] == ["s1", "w1:0", "a1"]
    seen = Event.objects.filter(round_id=board_round.pk, kind="alert.seen")
    assert seen.count() == 3 and {event.seat_side for event in seen} == {"defence"}


def test_alerts_page_by_detection_id_and_filter_by_engine_rule_and_source(as_defender, board_round, cyber_range, es,
                                                                         at):
    es.add("s1", suricata(stamp(at))).add("w1", modsecurity(stamp(at, 1), ip=CUSTOMER))
    service.ingest_alerts(board_round)

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
    service.ingest_alerts(board_round)
    as_defender.post(url(board_round, "ids/rules/apply/"), {"text": SEARCH_RULE, "base_version": 0}, format="json")

    shown = as_defender.get(url(board_round, "state/")).json()

    assert shown["round"] == board_round.pk and shown["phase"] == "running"
    assert shown["brief"]["title"] == "Placeholder round"
    assert shown["target"] == {"public_url": "http://board.com", "hosts": ["board.com"]}
    assert shown["objectives"] == [{"key": "board-auth-user-admin", "name": shown["objectives"][0]["name"],
                                    "state": "kept", "seen": False}]
    assert (shown["ids"], shown["waf"], shown["alerts_total"]) == ({"version": 1}, {"version": 0}, 1)


def test_an_attack_seat_reaches_no_defence_route(browser, board_round, make_user):
    attacker = make_user("attacker")
    rounds.seated(board_round, "attack", user=attacker)
    browser.force_authenticate(attacker)

    answer = browser.get(url(board_round, "ids/rules/"))

    assert answer.status_code == 403
    assert answer.json() == {"errors": [{"path": "", "code": "not_seated"}]}


def test_a_bot_defence_seat_reaches_its_side_with_its_token(browser, board_round):
    seat = rounds.seated(board_round, "defence", bot_name="defender-bot")
    token = issue_token(seat)

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

    answer = as_defender.post(url(board_round, "waf/check/"), {"posture": {"paranoia": 1}}, format="json")

    assert answer.status_code == 409
    assert answer.json()["errors"][0]["code"] == "round_not_started"


def test_the_round_start_posture_is_applied_to_both_engines(board_round, cyber_range):
    board_round.snapshot["round"]["posture"] = {"name": "start", "suricata_rules": SEARCH_RULE,
                                                "crs_tuning": {"paranoia": 3, "exclusions": []}}
    board_round.save()

    service.apply_posture(board_round)

    assert cyber_range.sensors["sensor"].rules == SEARCH_RULE
    assert "blocking_paranoia_level=3" in cyber_range.gateway.file
    assert [(one.engine, one.version) for one in service.versions(board_round, "ids")] == [("ids", 1)]
    assert [(one.engine, one.version) for one in service.versions(board_round, "waf")] == [("waf", 1)]

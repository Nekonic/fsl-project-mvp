from datetime import timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from telemetry import alerts as alert_feed
from telemetry import elastic
from telemetry.models import Detection, Event
from tests import rounds
from tests.training.defence.conftest import SEARCH_RULE
from training.defence import rules as service
from training.models import Round
from users.players import issue_token

BASE = "/api/rounds/{round}/defence/"
HTTP = "/etc/nginx/defence/http.conf"
ATTACKER = "198.51.100.9"
CUSTOMER = "203.0.113.50"
LATER_LOG = timedelta(seconds=1.5)


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


def read_due(found):
    Round.objects.filter(pk=found.pk).update(read_at=timezone.now() - timedelta(days=1))


def test_alerts_requests_store_each_alert_once_with_its_engine_rule_and_marker(as_defender, board_round, cyber_range,
                                                                              es, at):
    es.add("s1", suricata(stamp(at))).add("w1", modsecurity(stamp(at, 1))).add("a1", access(stamp(at, 2), 403))
    es.add("a2", access(stamp(at, 3), 200))

    read_due(board_round)
    first = as_defender.get(url(board_round, "alerts/")).json()
    read_due(board_round)
    as_defender.get(url(board_round, "alerts/"))

    assert [(row["engine"], row["rule"], row["request_id"], row["blocked"]) for row in first["alerts"]] == [
        ("ids", "1001", "m1", False), ("waf", "942100", "m2", False), ("waf", "403", None, True)]
    assert Detection.objects.filter(round=board_round).count() == 3
    assert [record.detection_id for record in alert_feed.detections(board_round)] == ["s1", "w1:0", "a1"]
    seen = Event.objects.filter(round_id=board_round.pk, kind="alert.seen")
    assert seen.count() == 3 and {event.player_side for event in seen} == {"defence"}


@pytest.mark.parametrize("first", ["modsecurity", "access"])
@pytest.mark.parametrize("marker", ["m2", None])
def test_a_request_modsecurity_refused_is_one_blocked_alert_not_a_second_access_log_one(board_round, cyber_range,
                                                                                       es, at, first, marker):
    modsecurity_at, access_at = (stamp(at), stamp(at, 1)) if first == "modsecurity" else (stamp(at, 1), stamp(at))
    refused = modsecurity(modsecurity_at, marker=marker or "")
    refused["transaction"]["response"] = {"http_code": 403}
    reads = {"modsecurity": ("w1", refused),
             "access": ("a1", dict(access(access_at, 403, marker=marker), request="GET /accounts/login/ HTTP/1.1"))}

    es.add(*reads[first])
    alert_feed.ingest_alerts(board_round)
    es.add(*reads["access" if first == "modsecurity" else "modsecurity"])
    alert_feed.ingest_alerts(board_round)

    assert [(row.rule, row.blocked) for row in Detection.objects.filter(round=board_round)] == [("942100", True)]


def test_an_alert_carrying_a_nul_character_is_stored_without_it_and_the_cursor_moves_on(board_round, cyber_range,
                                                                                       es, at):
    alert = suricata(stamp(at))
    alert["alert"]["signature"] = "Null byte\x00 in request"
    alert["http"]["url"] = "/?a=\x00"
    es.add("s1", alert)
    alert_feed.ingest_alerts(board_round)
    es.add("s2", suricata(stamp(at, 1), marker="m3"))
    alert_feed.ingest_alerts(board_round)

    rows = Detection.objects.filter(round=board_round).order_by("id")
    assert [(row.detection_id, row.signature, row.uri) for row in rows] == [
        ("s1", "Null byte in request", "/?a="), ("s2", "SQL injection in search", "/search/?q=x")]
    assert "\x00" not in str(rows[0].raw)


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
    read_due(board_round)

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
    assert later == {"alerts": [], "next": every["next"], "more": False, "total": 2}
    assert as_defender.get(url(board_round, "alerts/"), {"engine": "kql"}).status_code == 400


def test_traffic_counts_requests_and_refusals_by_origin_from_the_access_log(as_defender, board_round, cyber_range,
                                                                           es, at, monkeypatch):
    clock = [at + timedelta(seconds=elastic.SETTLE_SECONDS + 3.5)]
    monkeypatch.setattr("telemetry.access.read_now", lambda: clock[0])
    es.add("a1", access(stamp(at), 200)).add("a2", access(stamp(at, 1), 403)).add("a3", access(stamp(at, 2), 200,
                                                                                               ip=CUSTOMER))
    es.add("s1", suricata(stamp(at, 3)))

    first = as_defender.get(url(board_round, "traffic/")).json()
    es.add("a4", access(stamp(at, 4), 400))
    clock[0] = at + timedelta(minutes=1)
    second = as_defender.get(url(board_round, "traffic/"), {"after": first["next"]}).json()

    assert [(row["ip"], row["requests"], row["refused"]) for row in first["by_origin"]] == [
        (ATTACKER, 2, 1), (CUSTOMER, 1, 0)]
    assert [(row["ip"], row["requests"], row["refused"]) for row in second["by_origin"]] == [(ATTACKER, 1, 1)]
    assert as_defender.get(url(board_round, "traffic/"), {"after": "not-a-cursor"}).status_code == 400


def test_the_traffic_cursor_stays_one_timestamp_however_many_requests_share_a_second(as_defender, board_round,
                                                                                     cyber_range, es, at, monkeypatch):
    monkeypatch.setattr("telemetry.access.read_now", lambda: at + timedelta(minutes=1))
    for n in range(400):
        es.add(f"busy{n}", access(stamp(at), 200))

    first = as_defender.get(url(board_round, "traffic/")).json()
    second = as_defender.get(url(board_round, "traffic/"), {"after": first["next"]})

    assert [(row["ip"], row["requests"]) for row in first["by_origin"]] == [(ATTACKER, 400)]
    assert second.status_code == 200 and second.json()["by_origin"] == []
    assert len(first["next"]) < 100


def test_the_state_shows_the_brief_target_objectives_versions_and_alert_count(as_defender, board_round, cyber_range,
                                                                             es, at):
    es.add("s1", suricata(stamp(at)))
    alert_feed.ingest_alerts(board_round)
    service.apply_ids(board_round, SEARCH_RULE, 0)

    shown = as_defender.get(url(board_round, "state/")).json()

    assert shown["round"] == board_round.pk and shown["phase"] == "running"
    assert shown["brief"]["title"] == "Placeholder round"
    assert shown["target"] == {"public_url": "http://board.com", "hosts": ["board.com"]}
    assert shown["objectives"] == [{"key": "board-auth-user-admin", "name": shown["objectives"][0]["name"],
                                    "state": "kept", "seen": False}]
    assert (shown["ids"], shown["waf"], shown["alerts_total"]) == ({"version": 1}, {"version": 0}, 1)


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

    write = as_defender.post(url(board_round, "waf/apply/"), {"files": {HTTP: "deny all;\n"}, "base_version": 0},
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


def refused_request(at, marker, ip):
    found = modsecurity(at, marker=marker or "", ip=ip)
    found["transaction"]["response"] = {"http_code": 403}
    return found


def refused_access(at, marker, ip):
    return dict(access(at, 403, ip=ip, marker=marker), request="GET /accounts/login/ HTTP/1.1")


def detection_queries_of(found, es, pairs, at, reads, batch):
    for number in range(pairs):
        marker = f"m{batch}-{number}" if number % 2 else None
        es.add(f"{reads.__name__}-{batch}-{number}", reads(stamp(at, number / 100), marker, f"198.51.{batch}.{number}"))
    with CaptureQueriesContext(connection) as seen:
        alert_feed.ingest_alerts(found)
    return len([query for query in seen.captured_queries if "telemetry_detection" in query["sql"]])


@pytest.mark.parametrize("reads", [(refused_request, refused_access), (refused_access, refused_request)])
def test_blocked_requests_are_matched_with_queries_per_page_not_per_alert(board_round, cyber_range, es, at, reads):
    earlier, later = reads
    few = [detection_queries_of(board_round, es, 3, at, earlier, 1),
           detection_queries_of(board_round, es, 3, at + LATER_LOG, later, 1)]
    many = [detection_queries_of(board_round, es, 40, at + timedelta(hours=1), earlier, 2),
            detection_queries_of(board_round, es, 40, at + timedelta(hours=1) + LATER_LOG, later, 2)]

    assert few == many and max(many) <= 5
    rows = Detection.objects.filter(round=board_round)
    assert rows.count() == 43 and {(row.rule, row.blocked) for row in rows} == {("942100", True)}

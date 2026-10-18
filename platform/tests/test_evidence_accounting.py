import pytest

pytestmark = pytest.mark.django_db

from datetime import timedelta

from django.utils import timezone

def session_with(alerts_matching_no_case, benign_cases=2, benign_that_alerted=0):
    from api.models import Case, Detection, Session

    session = Session.objects.create()
    started = timezone.now()
    for index in range(benign_cases):
        Case.objects.create(
            session=session, case_id=f"benign-{index}", name=f"normal-{index}",
            malicious=False, correlation="marker",
            started_at=started, ended_at=started + timedelta(seconds=1),
        )
    Case.objects.create(
        session=session, case_id="attack-0", name="sqli", malicious=True,
        correlation="marker", started_at=started,
        ended_at=started + timedelta(seconds=1),
    )
    for index in range(alerts_matching_no_case):
        Detection.objects.create(
            session=session, detection_id=f"loose-{index}", source="suricata",
            signature="something the range did to itself", severity=2,
            timestamp=started, src_ip="172.30.0.4", marker=None, raw={},
        )
    for index in range(benign_that_alerted):
        Detection.objects.create(
            session=session, detection_id=f"benign-alert-{index}",
            source="suricata", signature="FSL SQLi attempt - URI", severity=2,
            timestamp=started, src_ip="172.30.0.4", marker=f"benign-{index}",
            raw={},
        )
    return session

def test_the_false_positive_rate_is_over_benign_cases_not_attacks(client):
    session = session_with(
        alerts_matching_no_case=0, benign_cases=3, benign_that_alerted=1
    )

    totals = client.get(f"/api/sessions/{session.id}/score/").json()

    assert (totals["fp"], totals["tn"], totals["fn"]) == (1, 2, 1)
    assert totals["benign_cases"] == 3
    assert totals["false_positive_rate"] == pytest.approx(1 / 3), (
        "one of three benign cases drew an alert. A rate over the one attack "
        "reads 1.0 and says every legitimate request was flagged"
    )

def test_no_alert_of_the_session_is_missing_from_the_accounting(client):
    from api.models import Detection

    session = session_with(alerts_matching_no_case=5, benign_that_alerted=1)
    Detection.objects.create(
        session=session, detection_id="attack-alert-0", source="suricata",
        signature="FSL SQLi attempt - URI", severity=2,
        timestamp=timezone.now(), src_ip="172.30.0.4", marker="attack-0", raw={},
    )

    totals = client.get(f"/api/sessions/{session.id}/score/").json()
    attributed = sum(len(c["detection_ids"]) for c in totals["per_case"])
    listed = client.get(f"/api/sessions/{session.id}/detections/").json()

    assert attributed == 2, attributed
    assert attributed + totals["unattributed"] == len(listed), (
        f"{len(listed)} alerts were ingested, {attributed} were attributed to "
        f"a case and {totals['unattributed']} were reported unattributed. The "
        f"difference is evidence that entered no number at all"
    )

def test_scoring_and_the_session_page_never_read_the_raw_alert_bodies(client):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    session = session_with(alerts_matching_no_case=5, benign_cases=1, benign_that_alerted=1)

    with CaptureQueriesContext(connection) as captured:
        assert client.get(f"/api/sessions/{session.id}/score/?brief=1").status_code == 200
        assert client.get(f"/api/sessions/{session.id}/").status_code == 200

    reads = [query["sql"] for query in captured if "api_detection" in query["sql"] and "SELECT" in query["sql"]]
    assert reads and not [sql for sql in reads if '"raw"' in sql], (
        "the result page asked for every alert body (the raw JSON) of a session that can hold tens of "
        "thousands of alerts; parsing them was most of the time the result tables took to fill in"
    )

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

def test_the_score_says_how_much_evidence_it_could_not_place(client):
    session = session_with(alerts_matching_no_case=7)

    totals = client.get(f"/api/sessions/{session.id}/score/").json()

    assert totals["unattributed"] == 7, (
        "seven alerts belonged to no case and the score reported only the "
        "three case decisions it could make. An operator reading fp=0 cannot "
        "see that the sensor fired seven times"
    )

def test_the_false_positive_denominator_is_on_screen(client):
    session = session_with(alerts_matching_no_case=0, benign_cases=3)

    totals = client.get(f"/api/sessions/{session.id}/score/").json()

    assert totals["benign_cases"] == 3, (
        "false_positive_rate = fp/(fp+tn) has a denominator equal to the "
        "number of benign cases - three here, six in the shipped file - so it "
        "has a granularity of 0.33 and is printed to two decimals"
    )

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

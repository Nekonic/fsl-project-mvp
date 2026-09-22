import pytest

pytestmark = pytest.mark.django_db

from datetime import timedelta

from django.utils import timezone

def session_with(alerts_matching_no_case, benign_cases=2):
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
    return session

def test_the_score_says_how_much_evidence_it_could_not_place(client):
    session = session_with(alerts_matching_no_case=7)

    totals = client.get(f"/api/sessions/{session.id}/score/").json()

    assert totals["unattributed"] == 7, (
        "seven alerts belonged to no case and the score reported only the "
        "sixteen decisions it could make. An operator reading fp=0 cannot see "
        "that the sensor was shouting the whole time"
    )

def test_the_false_positive_denominator_is_on_screen(client):
    session = session_with(alerts_matching_no_case=0, benign_cases=3)

    totals = client.get(f"/api/sessions/{session.id}/score/").json()

    assert totals["benign_cases"] == 3, (
        "false_positive_rate = fp/(fp+tn) has a denominator equal to the "
        "number of benign cases - three here, six in the shipped file - so it "
        "has a granularity of 0.33 and is printed to two decimals"
    )

def test_no_alert_of_the_session_is_missing_from_the_accounting(client):
    session = session_with(alerts_matching_no_case=5)

    totals = client.get(f"/api/sessions/{session.id}/score/").json()
    attributed = sum(len(c["detection_ids"]) for c in totals["per_case"])
    listed = client.get(f"/api/sessions/{session.id}/detections/").json()

    assert attributed + totals["unattributed"] == len(listed), (
        f"{len(listed)} alerts were ingested, {attributed} were attributed to "
        f"a case and {totals['unattributed']} were reported unattributed. The "
        f"difference is evidence that entered no number at all"
    )

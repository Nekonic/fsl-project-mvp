from datetime import datetime, timezone

OPENED = datetime(2026, 9, 18, 0, 0, 0, tzinfo=timezone.utc)


def open_session(client, at=OPENED):
    from api.models import Session

    session_id = client.post_json("/api/sessions/", {}).json()["id"]
    Session.objects.filter(pk=session_id).update(started_at=at)
    return session_id

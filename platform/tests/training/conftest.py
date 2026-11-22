import pytest


@pytest.fixture(autouse=True)
def no_wait_for_late_alerts(monkeypatch):
    monkeypatch.setattr("training.round.lifecycle.wait_for_late_alerts", lambda found: None)

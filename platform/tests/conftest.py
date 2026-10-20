import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from django.test import Client

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.append(str(REPO_ROOT))

class ApiClient(Client):

    def post_json(self, path, payload=None):
        return self.post(
            path, json.dumps(payload or {}), content_type="application/json"
        )

@pytest.fixture
def client():
    return ApiClient()

@pytest.fixture(autouse=True)
def nothing_remembered_between_tests():
    from api import site, views

    views._segments_kept.clear()
    site._records.clear()

@pytest.fixture(autouse=True)
def no_scenario_engine_thread():
    with patch("api.scenario_run.ensure_running", lambda: None):
        yield

@pytest.fixture(autouse=True)
def no_real_range(settings):
    from tests import standin

    settings.FSL_SUBSTRATE = "tests.standin.StandIn"
    with patch("api.views._aim_attacker", lambda adapter: None), \
            patch("subprocess.Popen", standin.refusing_docker()):
        yield

@pytest.fixture(autouse=True)
def no_real_board_read(request):
    if request.node.get_closest_marker("reads_ground_truth"):
        yield
        return
    def stand_in(wargame_id, host=""):
        return {"unit-test-account": "unit-test-hash"}

    with patch("api.views.loot.ground_truth", stand_in):
        yield

@pytest.fixture(autouse=True)
def no_real_effect_read(request):
    if request.node.get_closest_marker("reads_target_state"):
        yield
        return
    from api import effect

    def refuse_snapshot(*args, **kwargs):
        raise effect.StateUnavailable(
            "this unit test supplied no target; effect.snapshot was refused. A "
            "test that needs it must patch api.views.effect.snapshot or mark "
            "reads_target_state"
        )

    def refuse_changes(*args, **kwargs):
        raise effect.StateUnavailable(
            "this unit test supplied no database; effect.read_changes was "
            "refused. A test that needs it must patch api.views.effect.read_changes"
        )

    with patch("api.views.effect.snapshot", refuse_snapshot), \
            patch("api.views.effect.read_changes", refuse_changes):
        yield

@pytest.fixture(autouse=True)
def no_real_defense(request):
    if request.node.get_closest_marker("takes_defense"):
        yield
        return
    with patch("api.views._take_defense", lambda session, adapter, posture: None):
        yield

@pytest.fixture
def a_session_is_open(db):
    from api.models import Session

    return Session.objects.create(scenario="board", baseline=[])

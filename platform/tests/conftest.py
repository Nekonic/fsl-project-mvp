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
def no_real_substrate(request):
    import subprocess

    if request.node.get_closest_marker("stands_in_for_docker"):
        yield
        return

    real = subprocess.run

    def refuse(argv, **kwargs):
        if argv and argv[0] == "docker":
            from range.ports import RangeUnavailable

            raise RangeUnavailable(
                f"this unit test supplied no range, so {' '.join(argv[:3])} "
                f"was refused. Production code sees the same state when the "
                f"substrate is down; a test that needs a range must stub "
                f"api.views.substrate"
            )
        return real(argv, **kwargs)

    with patch("range.docker.subprocess.run", refuse):
        yield

@pytest.fixture(autouse=True)
def no_real_board_read(request):
    if request.node.get_closest_marker("reads_ground_truth"):
        yield
        return
    from api import loot

    def refuse(wargame_id):
        raise loot.GroundTruthUnavailable(
            f"this unit test supplied no board; ground_truth({wargame_id!r}) was "
            f"refused. A test that needs it must patch api.views.loot.ground_truth "
            f"or mark reads_ground_truth"
        )

    with patch("api.views.loot.ground_truth", refuse):
        yield

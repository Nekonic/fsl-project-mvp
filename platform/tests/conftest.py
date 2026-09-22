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
def no_settle(settings):
    settings.TARGET_SETTLE = 0

@pytest.fixture(autouse=True)
def no_real_substrate():
    import subprocess

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

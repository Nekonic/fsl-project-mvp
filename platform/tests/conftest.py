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
    def refuse(argv, **kwargs):
        raise AssertionError(
            f"a unit test reached the real substrate: {' '.join(argv)}"
        )

    with patch("range.docker.subprocess.run", refuse):
        yield

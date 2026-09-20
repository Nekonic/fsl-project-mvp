import json
import sys
from pathlib import Path

import pytest
from django.test import Client

# redteam is a sibling of the repository root. Putting the root on sys.path
# risks shadowing the stdlib `platform` module, but platform/ has no
# __init__.py and we always run with platform/ as the working directory, so
# `import platform` still resolves to the standard library.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.append(str(REPO_ROOT))


class ApiClient(Client):
    """Django's test client with a JSON POST shorthand.

    The API speaks plain Django now, so tests send bodies and read responses
    the same way the console and the harness do.
    """

    def post_json(self, path, payload=None):
        return self.post(
            path, json.dumps(payload or {}), content_type="application/json"
        )


@pytest.fixture
def client():
    return ApiClient()


@pytest.fixture(autouse=True)
def no_settle(settings):
    """Nothing to wait for: these tests mock the target.

    The real delay exists so consecutive red team cases land far enough apart
    for the target's own solve timestamps to tell them apart. With no target
    there is nothing to settle, and paying it on every recorded case turned a
    half-second suite into a ten-second one.
    """
    settings.TARGET_SETTLE = 0

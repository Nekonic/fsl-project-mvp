import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.append(str(REPO_ROOT))


@pytest.fixture(autouse=True)
def nothing_remembered_between_tests():
    from range import openstack

    openstack.forget()


@pytest.fixture(autouse=True)
def no_real_range(settings):
    from tests import standin

    settings.CR_SUBSTRATE = "tests.standin.StandIn"
    with patch("subprocess.Popen", standin.refusing_docker()):
        yield

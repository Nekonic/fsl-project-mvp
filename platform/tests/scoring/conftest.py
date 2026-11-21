import pytest

from tests.scoring import targets


@pytest.fixture
def board_target():
    return targets.board_target()


@pytest.fixture
def corp_target():
    return targets.corp_target()

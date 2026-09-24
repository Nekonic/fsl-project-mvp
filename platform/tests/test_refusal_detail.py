import pytest

from tests.test_judge_reachability import get, ranged

pytestmark = pytest.mark.django_db

@pytest.fixture(autouse=True)
def fresh_cache():
    from api import reachability

    yield
    reachability.forget()

def test_the_refusal_names_the_address_it_refused(client):
    with ranged():
        refused = get(client, "/api/rules/", "5.188.10.2")

    assert refused.status_code == 403
    assert "5.188.10.2" in refused.json()["detail"]

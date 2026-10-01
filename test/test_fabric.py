import requests

from conftest import PLATFORM_URL

def test_the_docker_range_answers_that_compose_builds_it(stack_is_up):
    response = requests.get(f"{PLATFORM_URL}/api/range/fabric/", timeout=30)

    assert response.status_code == 409, response.text[:300]
    assert "compose" in response.json()["detail"]

from unittest.mock import patch

import pytest

from range import images

URL = "/api/range/images/"

class Built:
    def __init__(self):
        self.ensured = 0
        self.cleaned = 0

    def plan_images(self):
        return images.Plan(
            images=(
                images.Image("fsl-waf", "d1", "ready", image="img-1"),
                images.Image("fsl-wg-board", "b1", "failed", builder="srv-2", detail="E: no mysql"),
            ),
            leftovers=(("image", "img-old", "image fsl-wiki was built from bundle d0"),),
        )

    def ensure_images(self):
        self.ensured += 1
        return self.plan_images()

    def clean_images(self):
        self.cleaned += 1
        return [("image", "img-old"), ("server", "srv-2")]

@pytest.fixture
def built():
    found = Built()
    with patch("api.views.substrate", lambda: found):
        yield found

def test_the_docker_range_builds_no_images(client):
    response = client.get(URL)

    assert response.status_code == 409, response.content
    assert "compose" in response.json()["detail"]

def test_reading_the_images_says_each_ones_state_and_why_it_failed(client, built):
    answer = client.get(URL).json()

    assert answer["images"][0] == {
        "host": "fsl-waf", "bundle": "d1", "state": "ready",
        "image": "img-1", "builder": "", "detail": "",
    }
    assert answer["images"][1]["detail"] == "E: no mysql"
    assert answer["leftovers"] == [{
        "kind": "image", "id": "img-old", "why": "image fsl-wiki was built from bundle d0",
    }]
    assert answer["clean"] is False and built.ensured == 0

def test_moving_the_builds_on_is_a_post(client, built):
    response = client.post_json(URL)

    assert response.status_code == 200 and built.ensured == 1

def test_clearing_failures_and_leftovers_is_a_delete_and_says_what_went(client, built):
    response = client.delete(URL)

    assert response.status_code == 200 and built.cleaned == 1
    assert response.json()["removed"] == [
        {"kind": "image", "id": "img-old"}, {"kind": "server", "id": "srv-2"},
    ]

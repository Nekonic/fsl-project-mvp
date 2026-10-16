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

def test_reading_the_images_changes_nothing_and_only_a_post_or_delete_acts_on_them(client, built):
    answer = client.get(URL).json()

    assert answer["images"][0] == {
        "host": "fsl-waf", "bundle": "d1", "state": "ready",
        "image": "img-1", "builder": "", "detail": "",
    }
    assert answer["images"][1]["detail"] == "E: no mysql"
    assert answer["leftovers"] == [{
        "kind": "image", "id": "img-old", "why": "image fsl-wiki was built from bundle d0",
    }]
    assert (built.ensured, built.cleaned) == (0, 0)

    assert client.post_json(URL).status_code == 200
    assert client.delete(URL).json()["removed"] == [
        {"kind": "image", "id": "img-old"}, {"kind": "server", "id": "srv-2"},
    ]
    assert (built.ensured, built.cleaned) == (1, 1)

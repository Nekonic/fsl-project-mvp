import pathlib
import re

COMPOSE = pathlib.Path(__file__).resolve().parent.parent.parent / "compose.yaml"

def images():
    return re.findall(r"^\s+image:\s*(\S+)", COMPOSE.read_text(), re.M)

def test_every_image_is_pinned_to_something_that_cannot_move():
    floating = [
        image for image in images()
        if "@sha256:" not in image and not re.search(r":\d", image)
    ]

    assert not floating, (
        f"these tags can move under the range without anyone touching the repo, "
        f"so the same commit scores differently on different days: {floating}"
    )

def test_the_sensor_and_the_target_are_pinned_by_digest():
    sensor = [i for i in images() if "suricata" in i]
    target = [i for i in images() if "juice-shop" in i]

    assert sensor and all("@sha256:" in i for i in sensor), sensor
    assert target and all("@sha256:" in i for i in target), target

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

def test_every_published_port_answers_on_loopback_only():
    published = re.findall(r"^\s+-\s+\"([^\"]+:\d+)\"\s*$", COMPOSE.read_text(), re.M)
    everywhere = [p for p in published if not p.startswith("127.0.0.1:")]

    assert published and not everywhere, (
        f"{everywhere} are published on every address, so each segment's gateway "
        f"forwards them back into the range and colima's forwarder offers them "
        f"to the whole LAN"
    )

def test_the_platform_s_store_outlives_the_checkout_that_started_it():
    import yaml

    compose = yaml.safe_load(COMPOSE.read_text())
    platform = compose["services"]["platform"]
    store = platform["environment"]["DJANGO_DB_PATH"].rsplit("/", 1)[0]
    mounted = {
        entry.split(":")[1]: entry.split(":")[0]
        for entry in platform["volumes"]
        if isinstance(entry, str) and entry.count(":") >= 1
    }

    assert mounted.get(store) in (compose.get("volumes") or {}), (
        f"{store} is mounted from {mounted.get(store)!r}, a directory inside "
        f"whichever checkout ran compose up. The sessions, cases and scores are "
        f"the only store there is, and removing that checkout removes them"
    )

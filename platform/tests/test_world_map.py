import importlib.util
import re
from importlib.machinery import SourceFileLoader
from json import dumps as js
from pathlib import Path

import pytest

from tests.browser import open_page

pytestmark = pytest.mark.django_db

ROOT = Path(__file__).resolve().parents[2]
WORLD = ROOT / "platform" / "console" / "templates" / "console" / "world.svg"

PLACES = {
    "Moscow": (37.61, 55.74),
    "Sao Paulo": (-46.63, -23.55),
    "Seoul": (126.978, 37.5665),
    "North Korea": (127.0, 40.0),
    "Reykjavik": (-21.94, 64.15),
    "Cape Town": (18.42, -33.92),
    "Wellington": (174.78, -41.29),
    "Anchorage": (-149.9, 61.22),
}
AT_SEA = {
    "South Atlantic": (-20.0, -30.0),
    "Central Pacific": (-150.0, 0.0),
    "Indian Ocean": (80.0, -20.0),
}

def generator():
    loader = SourceFileLoader("worldmap", str(ROOT / "bin/worldmap"))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader("worldmap", loader))
    loader.exec_module(module)
    return module

def rings():
    found = []
    for d in re.findall(r'd="([^"]+)"', WORLD.read_text()):
        for ring in re.findall(r"M([^Mz]+)z", d):
            numbers = [float(n) for n in re.findall(r"-?(?:\d+\.?\d*|\.\d+)", ring)]
            x, y = numbers[0], numbers[1]
            points = [(x, y)]
            for dx, dy in zip(numbers[2::2], numbers[3::2]):
                x, y = x + dx, y + dy
                points.append((x, y))
            found.append(points)
    return found

def on_land(x, y, drawn):
    inside = False
    for ring in drawn:
        for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
            if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
                inside = not inside
    return inside

def test_the_page_puts_a_point_where_the_generator_put_the_land(client):
    places = list(PLACES.values()) + list(AT_SEA.values()) + [(180.0, 0.0), (-180.0, -60.0)]
    seen = open_page(
        client, "/blue/1/",
        scenario=f"return {js(places)}.map(([lon, lat]) => projectOnMap(lon, lat));",
    )

    assert seen["errors"] == []
    world = generator()
    for (lon, lat), (x, y) in zip(places, seen["result"]):
        expected = world.project(lon, lat)
        assert (x, y) == pytest.approx(expected, abs=1e-9), (
            f"the page projects {lon}, {lat} to {x}, {y} and bin/worldmap drew "
            f"the land there at {expected}, so points would sit off their country"
        )

def test_the_page_frames_the_map_the_generator_drew(client):
    world = generator()
    page = client.get("/blue/1/").content.decode()

    assert f'viewBox="0 0 {world.WIDTH:g} {world.HEIGHT:g}"' in page

def test_known_cities_fall_on_land_and_open_sea_does_not():
    world, drawn = generator(), rings()

    misplaced = [name for name, place in PLACES.items() if not on_land(*world.project(*place), drawn)]
    flooded = [name for name, place in AT_SEA.items() if on_land(*world.project(*place), drawn)]

    assert misplaced == [] and flooded == []

def test_no_coastline_runs_across_the_map():
    spans = [
        round(abs(x2 - x1))
        for ring in rings()
        for (x1, _), (x2, _) in zip(ring, ring[1:] + ring[:1])
        if abs(x2 - x1) > 20
    ]

    assert spans == [], (
        "land that crosses the antimeridian was drawn as one ring, so its edge "
        "runs the width of the map"
    )

def test_an_island_on_the_antimeridian_is_cut_into_two_at_the_edges():
    fiji = [(179.0, -16.0), (-179.0, -16.0), (-179.0, -17.0), (179.0, -17.0), (179.0, -16.0)]

    pieces = list(generator().on_the_sphere(fiji))

    assert sorted(sorted({lon for lon, _ in piece}) for piece in pieces) == [
        [-180.0, -179.0], [179.0, 180.0],
    ]

def test_nothing_south_of_sixty_is_drawn():
    world = generator()
    lowest = max(y for ring in rings() for _, y in ring)

    assert lowest <= world.HEIGHT
    assert world.project(0, -60)[1] == pytest.approx(world.HEIGHT, abs=0.05)

MAP_COLOURS = ("--map-sea", "--map-land", "--map-border", "--map-point", "--map-line", "--map-target")

def test_the_map_takes_every_colour_from_one_set_of_variables():
    page = (WORLD.parent / "blue.html").read_text()
    markup = page[page.index('<svg viewBox'):page.index("</svg>")]
    drawing = page[page.index("async function renderMap"):page.index('getElementById("map-note")')]

    assert re.findall(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(", markup + drawing) == [], (
        "a colour written into the map itself has to be found and changed by "
        "hand when the console is rethemed"
    )
    assert [page.count(f"{name}:") for name in MAP_COLOURS] == [1] * len(MAP_COLOURS)
    assert [name for name in MAP_COLOURS if f"var({name})" not in page] == []

import ipaddress

import requests
import yaml

from range import DECLARATION

ELASTIC = "http://localhost:9200"

def declared_origins():
    document = yaml.safe_load(DECLARATION.read_text())
    return [
        origin
        for segment in document["segments"]
        for origin in segment.get("origins") or []
    ]

def test_every_origin_is_placed_in_its_country_by_the_pipeline_scoring_reads(stack_is_up):
    origins = declared_origins()
    sources = [
        {"_source": {"src_ip": str(address)}}
        for origin in origins
        for address in (next(ipaddress.ip_network(origin["subnet"]).hosts()),
                        list(ipaddress.ip_network(origin["subnet"]).hosts())[-1])
    ]
    placed = requests.post(
        f"{ELASTIC}/_ingest/pipeline/geoip/_simulate",
        json={"docs": sources},
        timeout=60,
    ).json()["docs"]
    geo = [doc["doc"]["_source"].get("src_geo", {}) for doc in placed]
    countries = [one.get("country_iso_code") for one in geo]
    unlocated = [source["_source"]["src_ip"] for source, one in zip(sources, geo) if not one.get("location")]

    misplaced = {
        origin["id"]: countries[2 * i: 2 * i + 2]
        for i, origin in enumerate(origins)
        if countries[2 * i: 2 * i + 2] != [origin["country"]] * 2
    }

    assert origins and not misplaced, (
        f"the map and the score place these origins somewhere other than the "
        f"country they are declared in: {misplaced}"
    )
    assert not unlocated, (
        f"GeoIP gave no location for {unlocated}, so the map cannot draw them; "
        f"run bin/fetch-geoip to populate config/ingest-geoip"
    )

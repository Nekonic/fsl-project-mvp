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
        f"{ELASTIC}/_ingest/pipeline/fsl-geoip/_simulate",
        json={"docs": sources},
        timeout=60,
    ).json()["docs"]
    countries = [doc["doc"]["_source"].get("src_geo", {}).get("country_iso_code") for doc in placed]

    misplaced = {
        origin["id"]: countries[2 * i: 2 * i + 2]
        for i, origin in enumerate(origins)
        if countries[2 * i: 2 * i + 2] != [origin["country"]] * 2
    }

    assert len(origins) == 30 and not misplaced, (
        f"the map and the score place these origins somewhere other than the "
        f"country they are declared in: {misplaced}"
    )

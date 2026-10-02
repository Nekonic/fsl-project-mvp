import requests

ELASTIC = "http://localhost:9200"
SETTING = "ingest.geoip.downloader.enabled"

def test_the_geoip_downloader_is_off(stack_is_up):
    nodes = requests.get(
        f"{ELASTIC}/_nodes/settings?flat_settings=true", timeout=30
    ).json().get("nodes", {})
    values = {node["settings"].get(SETTING) for node in nodes.values()}

    assert values == {"false"}, (
        f"{SETTING} is {values or 'unset'}, not {{'false'}}. With the managed "
        f"downloader on, a container recreate or a CDN the cloud cannot reach "
        f"leaves the range with no GeoIP database and every source unplaced. "
        f"The databases live in config/ingest-geoip instead (bin/fetch-geoip)."
    )

def test_geoip_places_a_source_without_the_downloader(stack_is_up):
    placed = requests.post(
        f"{ELASTIC}/_ingest/pipeline/fsl-geoip/_simulate",
        json={"docs": [{"_source": {"src_ip": "8.8.8.8"}}]},
        timeout=30,
    ).json()["docs"][0]["doc"]["_source"].get("src_geo", {})

    assert placed.get("country_iso_code") and placed.get("location"), (
        f"GeoIP resolved nothing from config/ingest-geoip with the downloader "
        f"off: {placed}. Run bin/fetch-geoip to populate the durable home."
    )

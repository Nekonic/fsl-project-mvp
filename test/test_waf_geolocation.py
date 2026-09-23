import json

import requests

from conftest import REPO_ROOT

PIPELINE = REPO_ROOT / "deploy/elastic/ingest-pipeline.json"
ELASTIC = "http://localhost:9200"


def test_the_pipeline_elasticsearch_runs_is_the_one_this_repo_declares(stack_is_up):
    live = requests.get(f"{ELASTIC}/_ingest/pipeline/fsl-geoip", timeout=60).json()

    assert live["fsl-geoip"]["processors"] == json.loads(PIPELINE.read_text())["processors"], (
        "Elasticsearch is running another pipeline than the one committed. "
        "Install it: curl -X PUT http://localhost:9200/_ingest/pipeline/fsl-geoip "
        "-H 'Content-Type: application/json' "
        "--data-binary @deploy/elastic/ingest-pipeline.json"
    )


def test_a_waf_record_is_placed_on_the_map_too(stack_is_up):
    simulated = requests.post(
        f"{ELASTIC}/_ingest/pipeline/_simulate",
        json={
            "pipeline": json.loads(PIPELINE.read_text()),
            "docs": [{"_source": {
                "fsl_source": "modsecurity",
                "transaction": {"client_ip": "177.54.144.4"},
            }}],
        },
        timeout=60,
    ).json()["docs"][0]["doc"]["_source"]

    assert simulated.get("src_geo", {}).get("location"), (
        "a ModSecurity record carries its source as transaction.client_ip and "
        "no src_ip, so the pipeline skipped it and every address only the WAF "
        f"caught was unplaced: {simulated}"
    )

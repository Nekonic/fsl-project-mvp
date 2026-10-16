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

import pathlib

from tests import composed

ROOT = pathlib.Path(__file__).resolve().parents[2]
FRONT = ROOT / "platform/nginx.conf"

def location(path):
    text = FRONT.read_text()
    start = text.index(f"location {path} {{")
    return text[start:text.index("}", start)]

def test_kibana_reads_the_same_elasticsearch_the_platform_ingests_from():
    kibana = composed.services()["kibana"]
    environment = kibana.get("environment") or {}

    assert environment.get("ELASTICSEARCH_HOSTS") == "http://elasticsearch:9200", (
        "the blue team reads the real ELK, so Kibana points at the same store "
        "the platform ingests from, not a copy"
    )
    assert "mgmt" in (kibana.get("networks") or []), (
        "Kibana reaches Elasticsearch over mgmt, where the store lives"
    )

def test_kibana_is_served_under_the_platform_s_one_port_by_path():
    kibana = composed.services()["kibana"]
    environment = kibana.get("environment") or {}

    assert environment.get("SERVER_BASEPATH") == "/kibana", environment
    assert environment.get("SERVER_REWRITEBASEPATH") == "true", environment
    assert not kibana.get("ports"), (
        "everything a person uses is on the platform's one port; Kibana is "
        "reached through it by path, not published on its own"
    )

    proxied = location("/kibana/")
    assert "kibana:5601" in proxied, proxied

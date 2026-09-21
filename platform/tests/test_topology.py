import json
from unittest.mock import patch

import pytest

import topology

NETWORKS = [
    {"Name": "fsl_edge",
     "Labels": {"fsl.origin": "Moscow, Russia", "fsl.segment": "Internet"},
     "IPAM": {"Config": [{"Subnet": "5.188.10.0/24", "Gateway": "5.188.10.1"}]},
     "Containers": {
         "aaa": {"Name": "fsl-waf", "IPv4Address": "5.188.10.4/24"},
         "bbb": {"Name": "fsl-proxy", "IPv4Address": "5.188.10.3/24"},
     }},
    {"Name": "fsl_estate", "Labels": {"fsl.segment": "Application estate"},
     "IPAM": {"Config": [{"Subnet": "172.30.0.0/24", "Gateway": "172.30.0.1"}]},
     "Containers": {
         "aaa": {"Name": "fsl-waf", "IPv4Address": "172.30.0.3/24"},
         "ccc": {"Name": "fsl-juice-shop", "IPv4Address": "172.30.0.2/24"},
     }},
    {"Name": "fsl_mgmt", "Labels": {},
     "IPAM": {"Config": [{"Subnet": "172.31.0.0/24", "Gateway": "172.31.0.1"}]},
     "Containers": {
         "ddd": {"Name": "fsl-elasticsearch", "IPv4Address": "172.31.0.2/24"},
     }},
]

MODES = {
    "fsl-waf": "fsl_edge",
    "fsl-proxy": "fsl_edge",
    "fsl-juice-shop": "fsl_estate",
    "fsl-elasticsearch": "fsl_mgmt",
                                                                             
                                                                      
    "fsl-suricata": "container:aaa",
}

class _Run:
    def __init__(self, networks=NETWORKS, modes=MODES, code=0, stderr=""):
        self.networks, self.modes, self.code, self.stderr = (
            networks, modes, code, stderr,
        )

    def __call__(self, argv, **kwargs):
        if argv[:3] == ["docker", "network", "ls"]:
            out = "\n".join(n["Name"] for n in self.networks)
        elif argv[:3] == ["docker", "network", "inspect"]:
            out = "\n".join(json.dumps(n) for n in self.networks)
        elif argv[:2] == ["docker", "ps"]:
            out = "\n".join(self.modes)
        else:
            out = "\n".join(f"{name} {mode}" for name, mode in self.modes.items())
        return type("R", (), {"returncode": self.code, "stdout": out,
                              "stderr": self.stderr})()

def shape(**kwargs):
    with patch("topology.subprocess.run", _Run(**kwargs)):
        return topology.shape()

def segment(found, segment_id):
    return next(s for s in found["segments"] if s["id"] == segment_id)

def test_every_segment_of_the_stack_is_on_the_picture():
    assert [s["id"] for s in shape()["segments"]] == ["edge", "estate", "mgmt"]

def test_the_outside_is_marked_as_outside():
    found = shape()

    assert segment(found, "edge")["outside"] is True
    assert segment(found, "estate")["outside"] is False

def test_outside_segments_come_first_because_that_is_the_way_in():
    assert shape()["segments"][0]["outside"] is True

def test_a_segment_is_called_something_a_person_can_read():
                                                                           
                                                                
    found = shape()

    assert segment(found, "edge")["name"] == "Internet"
    assert segment(found, "estate")["name"] == "Application estate"

def test_a_segment_nobody_named_falls_back_to_its_network_name():
                                                                           
                                             
    assert segment(shape(), "mgmt")["name"] == "mgmt"

def test_a_segment_carries_the_addresses_that_are_actually_on_it():
    estate = segment(shape(), "estate")

    assert {n["name"]: n["address"] for n in estate["nodes"]} == {
        "fsl-juice-shop": "172.30.0.2",
        "fsl-waf": "172.30.0.3",
    }
    assert estate["subnet"] == "172.30.0.0/24"

def test_a_box_with_a_foot_on_each_side_is_marked_as_a_way_in():
                                                                             
                                                                             
                             
    found = shape()
    crossings = {n["name"] for s in found["segments"] for n in s["nodes"]
                 if n["crosses"]}

    assert crossings == {"fsl-waf"}

def test_a_box_on_several_outside_segments_is_not_a_way_in():
                                                                             
                                                                             
                                                        
    networks = [dict(n) for n in NETWORKS]
    networks[2] = dict(networks[2], Labels={"fsl.origin": "Kwai Chung"},
                       Containers={"bbb": {"Name": "fsl-proxy",
                                           "IPv4Address": "172.31.0.9/24"}})
    crossings = {n["name"] for s in shape(networks=networks)["segments"]
                 for n in s["nodes"] if n["crosses"]}

    assert "fsl-proxy" not in crossings

def test_a_sensor_sharing_a_namespace_is_placed_where_it_watches():
                                                                             
                                      
    found = shape()

    assert found["sensors"] == [{"name": "fsl-suricata", "watches": "fsl-waf"}]

def test_the_sensor_appears_on_every_segment_it_can_see():
                                                                              
                                                    
    found = shape()
    watched = {s["id"] for s in found["segments"] if s["sensor"]}

    assert watched == {"edge", "estate"}

def test_docker_that_cannot_answer_is_an_error_not_an_empty_diagram():
                                                                           
                                                
    with pytest.raises(topology.StackUnavailable):
        shape(code=1, stderr="Cannot connect to the Docker daemon")

                                                                            
                                                                           
                                                                            
                                                              

pytestmark = pytest.mark.django_db

def _alert(doc_id, src_ip):
    return (doc_id, {
        "fsl_source": "suricata", "event_type": "alert",
        "timestamp": "2026-09-20T12:00:00Z", "src_ip": src_ip,
        "alert": {"signature": "FSL SQLi attempt", "severity": 1},
    })

@pytest.fixture
def drawn(client):
    session_id = client.post_json("/api/sessions/", {}).json()["id"]
    documents = [
        _alert("a", "5.188.10.3"), _alert("b", "5.188.10.5"),
        _alert("c", "172.30.0.3"), _alert("d", "10.9.9.9"),
    ]
    with patch("api.views.elastic.fetch", return_value=documents):
        client.post_json(f"/api/sessions/{session_id}/ingest/")
    with patch("api.views.topology.subprocess.run", _Run()):
        return client.get(f"/api/sessions/{session_id}/topology/").json()

def test_a_segment_carries_what_arrived_on_it(drawn):
    counted = {s["id"]: s["alerts"] for s in drawn["segments"]}

    assert counted["edge"] == 2
    assert counted["estate"] == 1

def test_a_segment_nothing_arrived_on_says_zero_rather_than_nothing(drawn):
    counted = {s["id"]: s["alerts"] for s in drawn["segments"]}

    assert counted["mgmt"] == 0

def test_an_address_on_no_segment_is_counted_rather_than_dropped(drawn):
                                                                           
                                                           
    assert drawn["unplaced"] == 1

def test_a_stack_that_cannot_be_read_is_503_not_a_blank_diagram(client):
    session_id = client.post_json("/api/sessions/", {}).json()["id"]

    with patch("api.views.topology.subprocess.run", _Run(code=1, stderr="no daemon")):
        response = client.get(f"/api/sessions/{session_id}/topology/")

    assert response.status_code == 503
    assert "daemon" in response.json()["detail"]

                                                                            
                                                                         
                                                                           
                                                                             
                                                                             
                                                        

def sources(client, session_id):
    with patch("api.views.topology.subprocess.run", _Run()):
        return client.get(f"/api/sessions/{session_id}/top/").json()["sources"]

@pytest.fixture
def counted(client):
    session_id = client.post_json("/api/sessions/", {}).json()["id"]
    documents = [
        _alert("a", "5.188.10.3"), _alert("b", "5.188.10.3"),
        _alert("c", "172.30.0.2"), _alert("d", "10.9.9.9"),
    ]
    with patch("api.views.elastic.fetch", return_value=documents):
        client.post_json(f"/api/sessions/{session_id}/ingest/")
    return sources(client, session_id)

def test_an_address_is_named_by_the_segment_it_belongs_to(counted):
    found = {s["src_ip"]: s for s in counted}

    assert found["5.188.10.3"]["zone"] == "Internet"
    assert found["5.188.10.3"]["outside"] is True
    assert found["172.30.0.2"]["zone"] == "Application estate"
    assert found["172.30.0.2"]["outside"] is False

def test_an_address_belonging_to_nothing_says_so_rather_than_guessing(counted):
    stranger = next(s for s in counted if s["src_ip"] == "10.9.9.9")

    assert stranger["zone"] == ""

def test_the_busiest_address_is_first_because_that_is_what_a_top_n_is(counted):
    assert [s["alerts"] for s in counted] == sorted(
        (s["alerts"] for s in counted), reverse=True
    )
    assert counted[0]["src_ip"] == "5.188.10.3"
    assert counted[0]["alerts"] == 2

def test_every_alert_is_counted_against_exactly_one_address(counted):
    assert sum(s["alerts"] for s in counted) == 4

def test_a_stack_that_cannot_be_read_still_reports_the_addresses(client):
                                                                         
                                 
    session_id = client.post_json("/api/sessions/", {}).json()["id"]
    with patch("api.views.elastic.fetch", return_value=[_alert("a", "5.188.10.3")]):
        client.post_json(f"/api/sessions/{session_id}/ingest/")

    with patch("api.views.topology.subprocess.run", _Run(code=1, stderr="no daemon")):
        found = client.get(f"/api/sessions/{session_id}/top/").json()["sources"]

    assert [s["src_ip"] for s in found] == ["5.188.10.3"]
    assert found[0]["zone"] == ""

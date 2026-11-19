import dataclasses
from pathlib import Path

import pytest

from cr import config, errors
from ingest.elastic import ElasticUnavailable
from range.runner import Drifted, RangeUnavailable
from rules.crs import TuningRefused
from rules.suricata import RuleApplyError, RuleSyntax, RulesUnreadable

ROOT = Path(__file__).resolve().parents[3]


def frozen_configs():
    return [value for value in vars(config).values()
            if isinstance(value, type) and dataclasses.is_dataclass(value) and value.__module__ == config.__name__]


@pytest.mark.parametrize("kind", frozen_configs(), ids=lambda kind: kind.__name__)
def test_every_seam_config_is_a_frozen_dataclass(kind):
    assert kind.__dataclass_params__.frozen


def test_the_config_is_built_from_the_topologies_and_the_environment():
    built = config.build({"ELASTIC_URL": "http://es.test:9200", "KIBANA_URL": "http://kb.test/kibana",
                          "BOARD_API_URL": "http://board.test:8000", "CR_JUMP_PORT": "2200",
                          "ATTACKER_TARGET_URL": "http://corp.com"}, ROOT)

    assert built.elastic.url == "http://es.test:9200" and built.elastic.index_of(3) == "logs-3-*"
    assert built.kibana.url == "http://kb.test/kibana" and Path(built.kibana.objects).is_file()
    assert built.ground_truth.board_url == "http://board.test:8000"
    assert built.jump.port == 2200
    assert (built.box.attacker, built.box.proxy, built.box.way_in) == ("cr-kali", "cr-kali", "cr-edge")
    assert built.box.target_url == "http://corp.com" and built.box.default_origin == "ru"
    assert built.box.tool_image == "cr-kali"
    assert built.waf.rules.startswith("/etc/nginx/modsecurity/crs/rules/") and built.waf.pid == "/run/nginx.pid"
    assert Path(built.range.declaration).is_file()


def test_an_empty_slot_index_falls_back_to_the_shared_index():
    assert config.ElasticConfig(slot_index="").index_of(2) == "logs-*"


def test_a_password_never_shows_in_a_repr():
    assert "hunter2" not in repr(config.OpenStackConfig(password="hunter2"))


def test_every_error_kind_has_a_status_and_its_own_code_among_its_codes():
    for kind in errors.KINDS:
        assert kind.code in kind.codes and 400 <= kind.status < 600
    assert len({kind.status for kind in errors.KINDS}) == len(errors.KINDS)


@pytest.mark.parametrize("raised, kind, code", [
    (RangeUnavailable("x"), errors.Unavailable, "range_unavailable"),
    (Drifted("x"), errors.Unavailable, "range_drifted"),
    (ElasticUnavailable("x"), errors.Unavailable, "elastic_unavailable"),
    (RulesUnreadable("x"), errors.Unavailable, "sensor_unavailable"),
    (RuleApplyError("x"), errors.EngineRefused, "apply_refused"),
    (RuleSyntax("x"), errors.EngineRefused, "suricata_syntax"),
    (TuningRefused("x"), errors.EngineRefused, "crs_refused"),
])
def test_seam_errors_are_domain_errors_with_a_known_code(raised, kind, code):
    assert isinstance(raised, kind) and raised.code == code and code in errors.CODES


def test_the_error_shape_is_a_list_of_paths_and_codes():
    refused = errors.Conflict("stale", code="stale_version", params={"current_version": 4})

    assert refused.status == 409
    assert refused.shown() == {"errors": [{"path": "", "code": "stale_version", "params": {"current_version": 4}}]}
    assert refused.params == {"current_version": 4}

    invalid = errors.Invalid(errors=(errors.FieldError(path="steps[3].check.params.case", code="invalid"),
                                     errors.FieldError(path="text", code="suricata_syntax", line=2)))
    assert invalid.shown()["errors"][1] == {"path": "text", "code": "suricata_syntax", "line": 2}

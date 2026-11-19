from pathlib import Path

from django.core.management import call_command

COMMITTED = Path(__file__).resolve().parents[3] / "openapi" / "schema.yaml"


def test_the_committed_schema_is_what_the_code_exports(tmp_path):
    exported = tmp_path / "schema.yaml"

    call_command("spectacular", "--file", str(exported), "--validate", "--fail-on-warn")

    assert COMMITTED.read_text() == exported.read_text(), (
        "openapi/schema.yaml is stale: run bin/gen-clients and commit openapi/schema.yaml")

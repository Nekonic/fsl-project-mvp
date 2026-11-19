import pytest
from drf_spectacular.generators import EndpointEnumerator, SchemaGenerator
from drf_spectacular.openapi import AutoSchema

from cr import errors

SCHEMA_ROUTES = {"/api/schema/", "/api/schema/attack/", "/api/schema/defence/"}
BODY_METHODS = {"post", "put", "patch"}
SIDES = ("attack", "defence")


def generated(monkeypatch=None):
    undeclared = {"request": set(), "responses": set()}
    if monkeypatch is not None:
        monkeypatch.setattr(AutoSchema, "get_request_serializer",
                            lambda schema: undeclared["request"].add((schema.path, schema.method.lower())))
        monkeypatch.setattr(AutoSchema, "get_response_serializers",
                            lambda schema: undeclared["responses"].add((schema.path, schema.method.lower())))
    return SchemaGenerator().get_schema(request=None, public=True), undeclared


@pytest.fixture(scope="module")
def schema():
    return generated()[0]


def operations(schema):
    return [(path, method, operation) for path, item in schema["paths"].items()
            for method, operation in item.items()]


def test_every_api_route_is_in_the_schema(schema):
    routed = {(path, method.lower()) for path, _, method, _ in EndpointEnumerator().get_api_endpoints()
              if path.startswith("/api/") and path not in SCHEMA_ROUTES and method not in ("OPTIONS", "HEAD")}

    assert sorted(routed - {(path, method) for path, method, _ in operations(schema)}) == []


def test_every_operation_declares_its_request_and_its_responses(monkeypatch):
    _, undeclared = generated(monkeypatch)

    assert sorted(undeclared["request"]) == []
    assert sorted(undeclared["responses"]) == []


def test_the_checker_sees_a_view_that_declares_nothing(monkeypatch, settings):
    settings.ROOT_URLCONF = "tests.contract.broken_urls"

    _, undeclared = generated(monkeypatch)

    assert ("/broken/", "get") in undeclared["responses"]


def test_every_request_body_is_a_serializer(schema):
    loose = [(path, method) for path, method, operation in operations(schema)
             if "requestBody" in operation
             and "$ref" not in operation["requestBody"]["content"]["application/json"]["schema"]]

    assert loose == []


def test_every_body_method_without_a_body_says_so_on_purpose(schema):
    bodiless = sorted((path, method) for path, method, operation in operations(schema)
                      if method in BODY_METHODS and "requestBody" not in operation)

    assert all(path.endswith(("/close/", "/heartbeat/", "/start/", "/end/", "/join/", "/forfeit/", "/logout/",
                              "/approve/", "/disable/", "/next/", "/record/", "/fabric/", "/pool/"))
               for path, _ in bodiless), bodiless


def test_every_success_response_has_a_serializer_unless_it_is_empty_by_status(schema):
    shapeless = []
    for path, method, operation in operations(schema):
        for status, answer in operation["responses"].items():
            if not str(status).startswith("2"):
                continue
            body = (answer.get("content") or {}).get("application/json", {}).get("schema")
            if str(status) == "204":
                if body is not None:
                    shapeless.append((path, method, status, "a 204 with a body"))
            elif not body:
                shapeless.append((path, method, status, "no serializer"))

    assert shapeless == []


def test_every_operation_answers_a_refusal_in_the_one_error_shape(schema):
    without = [(path, method) for path, method, operation in operations(schema)
               if operation["responses"].get("default", {}).get("content", {}).get("application/json", {})
               .get("schema", {}).get("$ref") != "#/components/schemas/Errors"]

    assert without == []


def test_every_attack_or_defence_operation_carries_exactly_its_one_side_tag(schema):
    wrong = []
    for path, method, operation in operations(schema):
        tags = set(operation.get("tags", ()))
        side = next((one for one in SIDES if f"/{one}/" in path.split("{round_id}", 1)[-1]), None)
        if side is not None and "/terminal-auth/" not in path and tags != {side}:
            wrong.append((path, method, sorted(tags)))
        if side is None and tags & set(SIDES):
            wrong.append((path, method, sorted(tags)))

    assert wrong == []


def test_every_domain_error_code_is_in_the_error_code_enum(schema):
    exported = set(schema["components"]["schemas"]["ErrorCodeEnum"]["enum"])

    assert sorted(errors.CODES - exported) == []
    assert sorted(exported - errors.CODES) == []


@pytest.mark.django_db
@pytest.mark.parametrize("side", SIDES)
def test_each_side_reads_a_schema_of_its_own_operations_only(browser, side):
    served = browser.get(f"/api/schema/{side}/", HTTP_ACCEPT="application/vnd.oai.openapi+json")

    assert served.status_code == 200
    tags = {tag for item in served.json()["paths"].values() for operation in item.values()
            for tag in operation["tags"]}
    assert tags == {side}
    assert "ErrorCodeEnum" in served.json()["components"]["schemas"]

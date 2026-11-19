from __future__ import annotations

from cr import errors

ERROR_CODE = "ErrorCodeEnum"
FIELD_ERROR = "FieldError"
ERRORS = "Errors"
SIDES = ("attack", "defence")
REFUSED = {"description": "refused",
           "content": {"application/json": {"schema": {"$ref": f"#/components/schemas/{ERRORS}"}}}}


def error_components(hp_named: bool) -> dict:
    shape = {
        "type": "object",
        "properties": {"errors": {"type": "array", "items": {"$ref": f"#/components/schemas/{FIELD_ERROR}"}}},
        "required": ["errors"],
    }
    if hp_named:
        shape["properties"]["hp"] = {"$ref": "#/components/schemas/HpBlock"}
    return {
        ERROR_CODE: {"type": "string", "enum": sorted(errors.CODES)},
        FIELD_ERROR: {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "code": {"$ref": f"#/components/schemas/{ERROR_CODE}"},
                "line": {"type": "integer"},
                "params": {"type": "object", "additionalProperties": {}},
            },
            "required": ["path", "code"],
        },
        ERRORS: shape,
    }


def error_shape(result, generator, request, public):
    schemas = result.setdefault("components", {}).setdefault("schemas", {})
    schemas.update(error_components("HpBlock" in schemas))
    for item in result.get("paths", {}).values():
        for operation in item.values():
            operation.setdefault("responses", {})["default"] = REFUSED
    return result


def tagged(result: dict, side: str) -> dict:
    paths = {}
    for path, item in result.get("paths", {}).items():
        operations = {method: operation for method, operation in item.items() if side in operation.get("tags", ())}
        if operations:
            paths[path] = operations
    result["paths"] = paths
    return result


def attack_only(result, generator, request, public):
    return tagged(result, "attack")


def defence_only(result, generator, request, public):
    return tagged(result, "defence")


def side_settings(side: str) -> dict:
    return {"POSTPROCESSING_HOOKS": ["drf_spectacular.hooks.postprocess_schema_enums", "cr.schema.error_shape",
                                     f"cr.schema.{side}_only"]}

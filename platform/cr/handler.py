from __future__ import annotations

import math
from typing import Any

from django.http import Http404, JsonResponse
from rest_framework import exceptions
from rest_framework.response import Response

from cr import errors

NON_FIELD_KEYS = {"non_field_errors", "detail"}

REFUSALS = (
    (exceptions.NotAuthenticated, errors.NotSignedIn),
    (exceptions.AuthenticationFailed, errors.NotSignedIn),
    (exceptions.PermissionDenied, errors.NotAPlayer),
    (exceptions.NotFound, errors.NotFound),
    (exceptions.MethodNotAllowed, errors.NotAllowed),
    (exceptions.NotAcceptable, errors.NotAcceptable),
    (exceptions.UnsupportedMediaType, errors.UnsupportedMedia),
    (exceptions.Throttled, errors.TooMany),
)


def joined(path: str, key: Any) -> str:
    if isinstance(key, int):
        return f"{path}[{key}]"
    if str(key) in NON_FIELD_KEYS:
        return path
    return f"{path}.{key}" if path else str(key)


def field_code(detail: Any) -> str:
    code = getattr(detail, "code", None) or "invalid"
    return code if code in errors.Invalid.codes else "invalid"


def flattened(detail: Any, path: str = "") -> list[errors.FieldError]:
    if isinstance(detail, dict):
        return [found for key, value in detail.items() for found in flattened(value, joined(path, key))]
    if isinstance(detail, list):
        if all(not isinstance(item, (dict, list)) for item in detail):
            return [errors.FieldError(path=path, code=field_code(item)) for item in detail]
        return [found for index, value in enumerate(detail) for found in flattened(value, joined(path, index))]
    return [errors.FieldError(path=path, code=field_code(detail))]


def refused_code(exc: exceptions.APIException, kind: type[errors.DomainError]) -> str:
    named = exc.get_codes() if isinstance(exc.detail, str) else None
    return named if isinstance(named, str) and named in kind.codes else kind.code


def domain_error(exc: Exception) -> errors.DomainError | None:
    if isinstance(exc, errors.DomainError):
        return exc
    if isinstance(exc, exceptions.ValidationError):
        return errors.Invalid(errors=tuple(flattened(exc.detail)) or (errors.FieldError(path="", code="invalid"),))
    if isinstance(exc, exceptions.ParseError):
        return errors.Invalid(code="malformed")
    if isinstance(exc, Http404):
        return errors.NotFound()
    if isinstance(exc, exceptions.Throttled):
        return errors.TooMany(params={"retry_after": math.ceil(exc.wait)} if exc.wait else None)
    for refused, kind in REFUSALS:
        if isinstance(exc, refused):
            return kind(code=refused_code(exc, kind))
    if isinstance(exc, ValueError):
        return errors.Invalid()
    if isinstance(exc, PermissionError):
        return errors.NotAPlayer()
    return None


def handle(exc: Exception, context: dict) -> Response | None:
    refused = domain_error(exc)
    if refused is None:
        return None
    answer = Response(refused.shown(), status=refused.status)
    retry_after = refused.params.get("retry_after")
    if isinstance(retry_after, int):
        answer["Retry-After"] = str(retry_after)
    challenge = challenge_of(context) if refused.status == 401 else None
    if challenge:
        answer["WWW-Authenticate"] = challenge
    return answer


def challenge_of(context: dict) -> str | None:
    view, request = context.get("view"), context.get("request")
    if view is None or request is None or not hasattr(view, "get_authenticate_header"):
        return None
    return view.get_authenticate_header(request)


def shaped(refused: errors.DomainError) -> JsonResponse:
    return JsonResponse(refused.shown(), status=refused.status)


def not_found(request, exception=None) -> JsonResponse:
    return shaped(errors.NotFound())


def denied(request, exception=None) -> JsonResponse:
    return shaped(errors.NotAPlayer())


def bad_request(request, exception=None) -> JsonResponse:
    return shaped(errors.Invalid())


def server_error(request) -> JsonResponse:
    return shaped(errors.ServerError())


def csrf_refused(request, reason: str = "") -> JsonResponse:
    return shaped(errors.NotAPlayer(code="csrf_failed"))

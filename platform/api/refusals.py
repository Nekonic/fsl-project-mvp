from django.core.exceptions import BadRequest
from django.http import Http404, JsonResponse

import attacker
import objectives
import operator_log
from ingest.elastic import ElasticUnavailable
from range.ports import RangeUnavailable
from rules.suricata import RuleApplyError, RulesUnreadable

UNAVAILABLE = (
    RangeUnavailable,
    RulesUnreadable,
    objectives.ObjectivesUnavailable,
    operator_log.OperatorLogUnavailable,
    ElasticUnavailable,
)


class Conflict(Exception):
    pass


class Refusals:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        if isinstance(exception, attacker.UnknownOrigin):
            raise Http404(str(exception)) from exception
        if isinstance(exception, UNAVAILABLE):
            return JsonResponse({"detail": str(exception)}, status=503)
        if isinstance(exception, (BadRequest, RuleApplyError)):
            return JsonResponse({"detail": str(exception)}, status=400)
        if isinstance(exception, Conflict):
            return JsonResponse({"detail": str(exception)}, status=409)
        return None


UNSAFE = frozenset({"POST", "PUT", "PATCH", "DELETE"})
FETCHED_BY_ITSELF = frozenset({"same-origin", "none"})


class SameOriginOnly:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method in UNSAFE:
            refused = _from_elsewhere(request)
            if refused:
                return JsonResponse({"detail": refused}, status=403)
            if request.body and request.content_type != "application/json":
                return JsonResponse({
                    "detail": f"the body must be application/json, got {request.content_type or 'nothing'}",
                }, status=415)
        return self.get_response(request)


def _from_elsewhere(request) -> str:
    fetched = request.headers.get("Sec-Fetch-Site")
    if fetched and fetched not in FETCHED_BY_ITSELF:
        return f"refused a {fetched} request: the platform only acts for its own pages"
    origin = request.headers.get("Origin")
    own = f"{request.scheme}://{request.get_host()}"
    if origin and origin != own:
        return f"refused a request from {origin}: the platform only acts for {own}"
    return ""

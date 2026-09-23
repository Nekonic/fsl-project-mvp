from django.core.exceptions import BadRequest
from django.http import JsonResponse

from range.ports import RangeUnavailable


class Refusals:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        if isinstance(exception, RangeUnavailable):
            return JsonResponse({"detail": str(exception)}, status=503)
        if isinstance(exception, BadRequest):
            return JsonResponse({"detail": str(exception)}, status=400)
        return None

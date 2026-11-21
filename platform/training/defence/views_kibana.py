import json

from drf_spectacular.utils import extend_schema
from rest_framework import negotiation, renderers
from rest_framework.response import Response
from rest_framework.views import APIView

from cr import strings
from training.defence import kibana_gate as service
from users import permissions as accounts

JSON = "application/json"


class Passthrough(renderers.BaseRenderer):
    media_type = JSON
    format = "json"
    charset = None

    def render(self, data, accepted_media_type=None, renderer_context=None):
        if isinstance(data, bytes):
            return data
        return json.dumps(data).encode()


class FirstRenderer(negotiation.BaseContentNegotiation):
    def select_parser(self, request, parsers):
        return parsers[0] if parsers else None

    def select_renderer(self, request, renderers, format_suffix=None):
        return renderers[0], renderers[0].media_type


class KibanaSession(accounts.SessionAuthentication):
    def enforce_csrf(self, request):
        return None


class KibanaGate(APIView):
    authentication_classes = [KibanaSession]
    renderer_classes = [Passthrough]
    content_negotiation_class = FirstRenderer
    parser_classes = []

    def answer(self, request):
        passed = service.kibana_gate(request.user, request.method, request.headers.get("X-Kibana-Uri", ""),
                                     request.headers, request.body)
        if passed.refused:
            return Response({"statusCode": passed.status, "error": passed.error,
                             "message": strings.line(passed.refused)}, status=passed.status, content_type=JSON)
        kept = dict(passed.headers)
        answer = Response(passed.body, status=passed.status, content_type=kept.pop("Content-Type", JSON))
        for name, value in kept.items():
            answer[name] = value
        return answer

    @extend_schema(exclude=True)
    def get(self, request):
        return self.answer(request)

    @extend_schema(exclude=True)
    def post(self, request):
        return self.answer(request)

    @extend_schema(exclude=True)
    def put(self, request):
        return self.answer(request)

    @extend_schema(exclude=True)
    def delete(self, request):
        return self.answer(request)

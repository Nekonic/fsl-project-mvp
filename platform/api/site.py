import itertools
import threading
import time
from collections import deque

import requests
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from api.models import Session

MARKER = "browse"
KEPT_PER_SESSION = 200
BODY_LIMIT = 64 * 1024
TIMEOUT = 60
BLOCKED = 403
PASSED_ON = ("Accept", "Accept-Language", "Content-Type", "User-Agent", "Referer", "Origin",
             "X-Forwarded-For")
NOT_RETURNED = {"connection", "content-encoding", "content-length", "keep-alive", "set-cookie",
                "transfer-encoding"}

_records: dict[int, deque] = {}
_numbers = itertools.count(1)
_lock = threading.Lock()


def waf_url(session_id: int) -> str:
    return f"http://fsl-{session_id}-waf-1"


def _text(body: bytes) -> dict:
    return {"text": body[:BODY_LIMIT].decode("utf-8", "replace"), "size": len(body),
            "truncated": len(body) > BODY_LIMIT}


def _keep(session_id: int, record: dict) -> None:
    with _lock:
        _records.setdefault(session_id, deque(maxlen=KEPT_PER_SESSION)).append(record)


def kept(session_id: int) -> list[dict]:
    with _lock:
        return list(_records.get(session_id, ()))


@csrf_exempt
def proxy(request, session_id, host):
    target = request.headers.get("X-Site-Uri") or "/"
    if not target.startswith("/"):
        raise Http404("the site path must start with /")
    sent = {name: request.headers[name] for name in PASSED_ON if name in request.headers}
    sent.update({"Host": host, "X-FSL-Case": MARKER, "Accept-Encoding": "identity"})
    body = request.body
    started = time.monotonic()
    try:
        answer = requests.request(request.method, waf_url(session_id) + target, headers=sent, data=body or None,
                                  allow_redirects=False, timeout=TIMEOUT)
    except requests.RequestException as exc:
        return HttpResponse(f"the session's WAF did not answer: {exc}", status=502, content_type="text/plain")
    returned = {name: value for name, value in answer.headers.items() if name.lower() not in NOT_RETURNED}
    _keep(session_id, {
        "id": next(_numbers),
        "at": time.time(),
        "method": request.method,
        "url": f"http://{host}{target}",
        "status": answer.status_code,
        "blocked": answer.status_code == BLOCKED,
        "ms": round((time.monotonic() - started) * 1000),
        "request_headers": sent,
        "response_headers": returned,
        "request_body": _text(body) if body else None,
        "response_body": _text(answer.content),
    })
    response = HttpResponse(answer.content, status=answer.status_code)
    for name, value in returned.items():
        response[name] = value
    return response


SUMMARY = ("id", "at", "method", "url", "status", "blocked", "ms")


@require_http_methods(["GET"])
def site_requests(request, session_id):
    get_object_or_404(Session, pk=session_id)
    try:
        after = int(request.GET.get("after", "0"), 10)
    except ValueError:
        return JsonResponse({"detail": '"after" must be a request id'}, status=400)
    return JsonResponse([{name: record[name] for name in SUMMARY}
                         for record in kept(session_id) if record["id"] > after], safe=False)


@require_http_methods(["GET"])
def site_request(request, session_id, request_id):
    get_object_or_404(Session, pk=session_id)
    for record in kept(session_id):
        if record["id"] == request_id:
            return JsonResponse(record)
    raise Http404(f"session {session_id} kept no request {request_id}")

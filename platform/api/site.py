import itertools
import threading
import time
from collections import deque

import requests
from django.http import Http404, HttpResponse, JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from api.models import Session
from range import substrate
from range.ports import RangeUnavailable

MARKER = "browse"
GATEWAY_ROLE = "gateway"
MARKER_HEADER = "X-FSL-Case"
KEPT_PER_SESSION = 200
BODY_LIMIT = 64 * 1024
TIMEOUT = (3, 20)
CHUNK = 8 * 1024
BLOCKED = 403
PASSED_ON = ("Accept", "Accept-Language", "Content-Type", "User-Agent", "Referer", "Origin")
NOT_RETURNED = {"connection", "content-encoding", "content-length", "keep-alive", "set-cookie",
                "transfer-encoding"}

_records: dict[int, deque] = {}
_wafs: dict[int, str] = {}
_numbers = itertools.count(1)
_lock = threading.Lock()


def waf_url(session_id: int) -> str:
    return f"http://fsl-{session_id}-waf-1"


def waf_of(session: Session) -> str:
    adapter = substrate()
    if not hasattr(adapter, "in_slot"):
        return waf_url(session.pk)
    with _lock:
        known = _wafs.get(session.pk)
    if known:
        return known
    found = f"http://{adapter.in_slot(session.slot or 1).address(GATEWAY_ROLE)}"
    with _lock:
        _wafs[session.pk] = found
    return found


def _text(body: bytes, size: int) -> dict:
    return {"text": body[:BODY_LIMIT].decode("utf-8", "replace"), "size": size,
            "truncated": size > BODY_LIMIT}


def _keep(session_id: int, record: dict) -> None:
    with _lock:
        _records.setdefault(session_id, deque(maxlen=KEPT_PER_SESSION)).append(record)


def kept(session_id: int) -> list[dict]:
    with _lock:
        return list(_records.get(session_id, ()))


def forget(session_id: int) -> None:
    with _lock:
        _records.pop(session_id, None)
        _wafs.pop(session_id, None)


def _peer(answer) -> str:
    for socket_of in (lambda: answer.raw.connection.sock, lambda: answer.raw._fp.fp.raw._sock):
        try:
            return socket_of().getpeername()[0]
        except (AttributeError, OSError, TypeError, IndexError):
            continue
    return ""


def shown_marker(session: Session, text: str) -> str:
    return text.replace(session.browse_marker, MARKER) if isinstance(text, str) else text


@csrf_exempt
def proxy(request, session_id, host):
    session = get_object_or_404(Session, pk=session_id)
    if session.ended_at is not None:
        return HttpResponse(f"session {session_id} is closed", status=409, content_type="text/plain")
    target = request.headers.get("X-Site-Uri") or "/"
    if not target.startswith("/"):
        raise Http404("the site path must start with /")
    sent = {name: request.headers[name] for name in PASSED_ON if name in request.headers}
    sent.update({"Host": host, MARKER_HEADER: session.browse_marker, "Accept-Encoding": "identity"})
    body = request.body
    started = time.monotonic()
    try:
        answer = requests.request(request.method, waf_of(session) + target, headers=sent, data=body or None,
                                  allow_redirects=False, timeout=TIMEOUT, stream=True)
    except (requests.RequestException, RangeUnavailable):
        return HttpResponse("the session's WAF did not answer", status=502, content_type="text/plain")
    returned = {name: value for name, value in answer.headers.items() if name.lower() not in NOT_RETURNED}
    record = {
        "id": next(_numbers),
        "at": time.time(),
        "method": request.method,
        "url": f"http://{host}{target}",
        "to": _peer(answer),
        "status": answer.status_code,
        "blocked": answer.status_code == BLOCKED,
        "request_headers": dict(sent, **{MARKER_HEADER: MARKER}),
        "response_headers": returned,
        "request_body": _text(body, len(body)) if body else None,
    }

    def passed_on():
        head, size = bytearray(), 0
        try:
            for chunk in answer.iter_content(CHUNK):
                size += len(chunk)
                if len(head) < BODY_LIMIT:
                    head += chunk[:BODY_LIMIT - len(head)]
                yield chunk
        except requests.RequestException:
            return
        finally:
            answer.close()
            record.update(ms=round((time.monotonic() - started) * 1000), response_body=_text(bytes(head), size))
            _keep(session_id, record)

    response = StreamingHttpResponse(passed_on(), status=answer.status_code)
    for name, value in returned.items():
        response[name] = value
    return response


SUMMARY = ("id", "at", "method", "url", "status", "blocked", "ms")


@require_http_methods(["GET"])
def site_requests(request, session_id):
    session = get_object_or_404(Session, pk=session_id)
    if session.ended_at is not None:
        return JsonResponse({"detail": f"session {session_id} is closed"}, status=409)
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

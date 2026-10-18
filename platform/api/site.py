import http.client
import itertools
import re
import socket
import threading
import time
import zlib
from collections import deque
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from http import HTTPStatus
from http.cookies import CookieError, SimpleCookie
from urllib.parse import urljoin, urlsplit

from django.conf import settings
from django.http import Http404, HttpResponse, JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

import attacker
from api import customers
from api.models import Session
from range import substrate
from range.ports import RangeUnavailable, Shape
from range.slot import NAMED_ON

MARKER = "browse"
GATEWAY_ROLE = "gateway"
ATTACKER_ROLE = "attacker"
SCORER_ROLE = "scorer"
SNAT = "snat"
SITE_PORT = 80
MARKER_HEADER = "X-Request-ID"
KEPT_PER_SESSION = 200
BODY_LIMIT = 64 * 1024
TIMEOUT = (3, 20)
CHUNK = 8 * 1024
BLOCKED = 403
PASSED_ON = ("Accept", "Accept-Language", "Content-Type", "User-Agent", "Referer", "Origin")
ENCODINGS = "gzip, deflate"
CHROME_ORDER = ("Host", "Connection", "Content-Length", "Origin", "Content-Type", "Upgrade-Insecure-Requests",
                "User-Agent", "Accept", "Referer", "Accept-Encoding", "Accept-Language", "Cookie", MARKER_HEADER)
BODIED = ("POST", "PUT", "PATCH")
FAVICON = "/favicon.ico"
FAVICON_ACCEPT = "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8"
CACHE_WAIT = 1.5
NOT_RETURNED = {"connection", "content-length", "keep-alive", "set-cookie", "transfer-encoding"}
GZIP = {"gzip", "x-gzip"}
SUBRESOURCE_TAG = re.compile(r"<(link|script|img)\b([^>]*)>", re.IGNORECASE)
SUBRESOURCE_URL = re.compile(r"""\b(?:href|src)\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
SITE_PAGE = re.compile(r"^https?://[^/]+/site/\d+/([a-z0-9.-]+)(/[^#]*)?$")
NO_POLICY_SENT = "strict-origin-when-cross-origin"
DESTINATIONS = {"document": "document", "iframe": "document", "frame": "document", "style": "stylesheet",
                "script": "script", "image": "image", "font": "font", "empty": "fetch", "favicon": "other"}
BY_CONTENT = (("text/html", "document"), ("text/css", "stylesheet"), ("javascript", "script"),
              ("image/", "image"), ("font/", "font"))
CATEGORIES = {"document": "doc", "stylesheet": "css", "script": "js", "image": "img", "fetch": "xhr",
              "font": "font", "other": "other"}
NAMED_BY_MIME = {"image", "other"}

_records: dict[int, deque] = {}
_egresses: dict[int, tuple] = {}
_policies: dict[int, str] = {}
_jars: dict[tuple, dict] = {}
_favicons: set[tuple] = set()
_numbers = itertools.count(1)
_lock = threading.Lock()


@dataclass(frozen=True)
class Egress:
    source: str
    address: str
    port: int
    boxed: bool

    @property
    def remote(self) -> str:
        return f"{self.address}:{self.port}"


def _adapter(session: Session):
    adapter = substrate()
    if hasattr(adapter, "in_slot"):
        return adapter.in_slot(session.slot or 1)
    if hasattr(adapter, "for_session"):
        return adapter.for_session(session.pk)
    return adapter


def _standing(segments, segment_id: str, host: str) -> str:
    return next((node.address for segment in segments if segment.id == segment_id
                 for node in segment.nodes if node.name == host), "")


def _customers_origin(session: Session, segments, unbound: str) -> dict:
    offered = attacker.customer_origins(Shape(segments=tuple(segments), sensors=()), unbound)
    if not offered:
        raise RangeUnavailable("the range offers the customers no origin, so the Website pane has no "
                               "customers address to send from")
    try:
        weights = customers.declared(session.scenario)["origins"]
    except customers.NoTraffic:
        weights = {}
    return min(offered, key=lambda origin: (-weights.get(origin["id"], 0), origin["id"]))


def found_egress(session: Session, adapter) -> Egress:
    declared = settings.RANGE
    segments = adapter.segments()
    gateway = declared.host(GATEWAY_ROLE)
    if settings.ATTACKER_ORIGIN_MODE == SNAT:
        origin = _customers_origin(session, segments, attacker.unbound_source(adapter.runner(ATTACKER_ROLE)))
        address = _standing(segments, NAMED_ON, gateway)
        if not origin["addresses"] or not address:
            raise RangeUnavailable(f"no customers address on {origin['id']!r}, or {gateway} has no {NAMED_ON} "
                                   f"address for board.com")
        return Egress(source=origin["addresses"][0], address=address, port=SITE_PORT, boxed=True)
    origin = _customers_origin(session, segments, "")
    source = _standing(segments, origin["id"], declared.host(SCORER_ROLE))
    address = _standing(segments, origin["id"], gateway)
    if not source or not address:
        raise RangeUnavailable(f"the platform and {gateway} do not both stand on the customers network "
                               f"{origin['id']!r}")
    return Egress(source=source, address=address, port=SITE_PORT, boxed=False)


def egress_of(session: Session) -> tuple[Egress, object]:
    with _lock:
        known = _egresses.get(session.pk)
    if known:
        return known
    adapter = _adapter(session)
    found = (found_egress(session, adapter), adapter)
    with _lock:
        _egresses[session.pk] = found
    return found


def opened(egress: Egress, adapter) -> socket.socket:
    if egress.boxed:
        line = adapter.opened(ATTACKER_ROLE, attacker.as_customer(egress.source, egress.address, egress.port))
    else:
        line = socket.create_connection((egress.address, egress.port), TIMEOUT[0], (egress.source, 0))
    line.settimeout(TIMEOUT[1])
    return line


def exchange(egress: Egress, adapter, method: str, target: str, headers: dict, body: bytes):
    connection = http.client.HTTPConnection(egress.address, egress.port, timeout=TIMEOUT[1])
    connection.sock = opened(egress, adapter)
    try:
        connection.request(method, target, body=body or None, headers=headers)
        return connection, connection.getresponse()
    except BaseException:
        connection.close()
        raise


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
        _egresses.pop(session_id, None)
        _policies.pop(session_id, None)
        for key in [key for key in _jars if key[0] == session_id]:
            del _jars[key]
        _favicons.difference_update({key for key in _favicons if key[0] == session_id})


def shown_marker(session: Session, text: str) -> str:
    return text.replace(session.browse_marker, MARKER) if isinstance(text, str) else text


def as_browsed(name: str, value: str, host: str) -> str:
    if name == "Origin":
        return value if value == "null" else f"http://{host}"
    if name == "Referer":
        found = SITE_PAGE.match(value)
        return f"http://{found[1]}{found[2] or '/'}" if found else ""
    return value


def kind_of(destination: str, content_type: str) -> tuple[str, str]:
    mime = content_type.split(";")[0].strip().lower()
    kind = DESTINATIONS.get(destination) or next(
        (named for part, named in BY_CONTENT if part in mime), "other")
    shown = re.sub(r"^(application|image)/", "", mime) if kind in NAMED_BY_MIME and mime else kind
    return shown, CATEGORIES[kind]


def _policy(session_id: int, referred: bool) -> str:
    with _lock:
        return _policies.get(session_id, NO_POLICY_SENT) if referred else NO_POLICY_SENT


def _learn_policy(session_id: int, category: str, headers: list) -> None:
    if category != "doc":
        return
    sent = [value for name, value in headers if name.lower() == "referrer-policy"]
    policy = sent[-1].split(",")[-1].strip().lower() if sent else NO_POLICY_SENT
    with _lock:
        _policies[session_id] = policy


def phrase_of(status: int) -> str:
    try:
        return HTTPStatus(status).phrase
    except ValueError:
        return ""


def _transferred(answer, headers: list, size: int) -> int:
    head = f"HTTP/1.1 {answer.status} {answer.reason}\r\n" + "".join(f"{n}: {v}\r\n" for n, v in headers) + "\r\n"
    return len(head.encode("latin-1", "replace")) + size


def _cookie_header(session_id: int, host: str, target: str) -> str:
    path = urlsplit(target).path or "/"
    with _lock:
        jar = dict(_jars.get((session_id, host), {}))
    return "; ".join(f"{name}={value}" for name, (value, scope) in jar.items()
                     if scope == "/" or path == scope or path.startswith(scope.rstrip("/") + "/"))


def _expired(morsel) -> bool:
    if morsel["max-age"]:
        try:
            return int(morsel["max-age"]) <= 0
        except ValueError:
            return False
    if morsel["expires"]:
        try:
            return parsedate_to_datetime(morsel["expires"]).timestamp() <= time.time()
        except (TypeError, ValueError):
            return False
    return False


def _keep_cookies(session_id: int, host: str, headers: list) -> None:
    for name, value in headers:
        if name.lower() != "set-cookie":
            continue
        try:
            parsed = SimpleCookie(value)
        except CookieError:
            continue
        with _lock:
            jar = _jars.setdefault((session_id, host), {})
            for morsel in parsed.values():
                if morsel["secure"]:
                    continue
                if _expired(morsel):
                    jar.pop(morsel.key, None)
                else:
                    jar[morsel.key] = (morsel.value, morsel["path"] or "/")


def _outgoing(session: Session, host: str, method: str, target: str, browsed: dict, body: bytes,
              document: bool) -> dict:
    headers = {"Host": host, "Connection": "keep-alive", **browsed, "Accept-Encoding": ENCODINGS,
               MARKER_HEADER: session.browse_marker}
    if method in BODIED:
        headers["Content-Length"] = str(len(body))
    if document:
        headers["Upgrade-Insecure-Requests"] = "1"
    if cookie := _cookie_header(session.pk, host, target):
        headers["Cookie"] = cookie
    return {name: headers[name] for name in CHROME_ORDER if name in headers}


def _decoder(answer):
    encoding = (answer.getheader("Content-Encoding") or "").strip().lower()
    if encoding in GZIP:
        return zlib.decompressobj(zlib.MAX_WBITS | 16)
    if encoding == "deflate":
        return zlib.decompressobj()
    return None


def _pieces(answer, decoder):
    while chunk := answer.read(CHUNK):
        yield len(chunk), decoder.decompress(chunk) if decoder else chunk
    if decoder:
        yield 0, decoder.flush()


def _entry(session_id: int, method: str, host: str, target: str, sent: dict, answer, egress: Egress,
           destination: str, body: bytes) -> dict:
    shown_type, category = kind_of(destination, answer.getheader("Content-Type", ""))
    received = [[name, value] for name, value in answer.getheaders()]
    referer = sent.get("Referer", "")
    return {
        "id": next(_numbers),
        "at": time.time(),
        "method": method,
        "url": f"http://{host}{target}",
        "status": answer.status,
        "status_text": answer.reason or phrase_of(answer.status),
        "blocked": answer.status == BLOCKED,
        "type": shown_type,
        "category": category,
        "initiator": {"type": "parser", "url": referer} if referer and category != "doc" else {"type": "other"},
        "egress": egress.source,
        "remote_address": egress.remote,
        "referrer_policy": _policy(session_id, bool(referer)),
        "request_headers": [[name, value] for name, value in sent.items() if name != MARKER_HEADER],
        "response_headers": received,
        "request_body": _text(body, len(body)) if body else None,
        "cache": "",
        "body_size": 0,
    }


def _relay(session_id: int, record: dict, connection, answer, started: float, after=None):
    decoder = _decoder(answer)
    head, size, raw = bytearray(), 0, 0
    try:
        for read, data in _pieces(answer, decoder):
            raw += read
            size += len(data)
            if len(head) < BODY_LIMIT:
                head += data[:BODY_LIMIT - len(head)]
            if data:
                yield data
    except (OSError, http.client.HTTPException, zlib.error):
        return
    finally:
        connection.close()
        record.update(ms=round((time.monotonic() - started) * 1000),
                      size=_transferred(answer, record["response_headers"], raw), body_size=size,
                      response_body=_text(bytes(head), size))
        _keep(session_id, record)
        if after:
            after(record)


def _later(delay: float, work, *args) -> None:
    timer = threading.Timer(delay, work, args)
    timer.daemon = True
    timer.start()


def _subresources(page: str, url: str) -> list[str]:
    here = urlsplit(url)
    found = []
    for tag, attributes in SUBRESOURCE_TAG.findall(page):
        reference = SUBRESOURCE_URL.search(attributes)
        if not reference or (tag.lower() == "link" and "stylesheet" not in attributes.lower()):
            continue
        joined = urlsplit(urljoin(url, reference[1]))
        if joined.netloc == here.netloc:
            found.append(f"http://{joined.netloc}{joined.path or '/'}{'?' + joined.query if joined.query else ''}")
    return list(dict.fromkeys(found))


def _list_cached(session_id: int, document: dict, wanted: list[str]) -> None:
    for url in wanted:
        with _lock:
            seen = [record for record in _records.get(session_id, ()) if record["url"] == url]
        before = [record for record in seen if record["at"] < document["at"] and record["status"] == 200
                  and not record["cache"] and record["category"] != "doc"]
        if before and not any(record["at"] >= document["at"] for record in seen):
            _keep(session_id, {**before[-1], "id": next(_numbers), "at": time.time(), "cache": "disk",
                               "initiator": {"type": "parser", "url": document["url"]}, "size": 0, "ms": 0})


def _fetch_favicon(session: Session, host: str, egress: Egress, adapter, browsed: dict) -> None:
    asked = {name: browsed[name] for name in ("User-Agent", "Accept-Language") if name in browsed}
    sent = _outgoing(session, host, "GET", FAVICON, {**asked, "Accept": FAVICON_ACCEPT}, b"", False)
    started = time.monotonic()
    try:
        connection, answer = exchange(egress, adapter, "GET", FAVICON, sent, b"")
    except (OSError, http.client.HTTPException):
        return
    record = _entry(session.pk, "GET", host, FAVICON, sent, answer, egress, "favicon", b"")
    _keep_cookies(session.pk, host, record["response_headers"])
    for _ in _relay(session.pk, record, connection, answer, started):
        pass


@csrf_exempt
def proxy(request, session_id, host):
    session = get_object_or_404(Session, pk=session_id)
    if session.ended_at is not None:
        return HttpResponse(f"session {session_id} is closed", status=409, content_type="text/plain")
    target = request.headers.get("X-Site-Uri") or "/"
    if not target.startswith("/"):
        raise Http404("the site path must start with /")
    destination = request.headers.get("Sec-Fetch-Dest", "")
    browsed = {name: as_browsed(name, request.headers[name], host) for name in PASSED_ON if name in request.headers}
    browsed = {name: value for name, value in browsed.items() if value}
    body = request.body
    sent = _outgoing(session, host, request.method, target, browsed, body, DESTINATIONS.get(destination) == "document")
    started = time.monotonic()
    try:
        egress, adapter = egress_of(session)
        connection, answer = exchange(egress, adapter, request.method, target, sent, body)
    except http.client.InvalidURL:
        return HttpResponse("the site path is not a valid request target", status=400, content_type="text/plain")
    except (OSError, http.client.HTTPException, RangeUnavailable):
        return HttpResponse("board.com did not answer", status=502, content_type="text/plain")
    record = _entry(session_id, request.method, host, target, sent, answer, egress, destination, body)
    _learn_policy(session_id, record["category"], record["response_headers"])
    _keep_cookies(session_id, host, record["response_headers"])

    def after_document(finished):
        if finished["category"] != "doc":
            return
        _later(CACHE_WAIT, _list_cached, session_id, finished,
               _subresources(finished["response_body"]["text"], finished["url"]))
        with _lock:
            first = (session_id, host) not in _favicons
            _favicons.add((session_id, host))
        if first:
            _later(0, _fetch_favicon, session, host, egress, adapter, browsed)

    response = StreamingHttpResponse(_relay(session_id, record, connection, answer, started, after_document),
                                     status=answer.status)
    dropped = NOT_RETURNED | ({"content-encoding"} if _decoder(answer) else set())
    for name, value in record["response_headers"]:
        if name.lower() not in dropped:
            response[name] = value
    return response


SUMMARY = ("id", "at", "method", "url", "status", "status_text", "type", "category", "initiator", "size", "ms",
           "body_size", "cache")


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
            return JsonResponse({name: value for name, value in record.items() if name != "blocked"})
    raise Http404(f"session {session_id} kept no request {request_id}")

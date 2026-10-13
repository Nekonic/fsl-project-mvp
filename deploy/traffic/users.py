import gzip
import http.client
import json
import os
import re
import signal
import sys
import threading
import time
import uuid
import zlib
from datetime import datetime, timezone
from urllib.parse import urlencode, urlsplit

MARKER = "X-FSL-Case"
TOKEN = re.compile(rb'name="csrfmiddlewaretoken" value="([^"]+)"')
CSRF_REFUSED = b"CSRF verification failed"
REDIRECTS = (301, 302, 303, 307, 308)
TIMEOUT = 10
BODY_KEPT = 1 << 20
WORKERS_MAX = 64
LOOK_EVERY = 1.0
ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"


class Pace:
    def __init__(self, rate):
        self.lock = threading.Lock()
        self.rate = rate
        self.due = time.monotonic()

    def wait(self):
        with self.lock:
            self.due = max(self.due, time.monotonic()) + 1.0 / self.rate
            due = self.due
        time.sleep(max(0.0, due - time.monotonic()))


class Answer:
    def __init__(self, source=""):
        self.status = 0
        self.location = ""
        self.page = b""
        self.cookies = []
        self.source = source


def opened(page, encoding):
    try:
        if encoding == "gzip":
            return gzip.decompress(page)
        if encoding == "deflate":
            return zlib.decompress(page)
    except (OSError, zlib.error):
        return b""
    return page


def target_path(location):
    parts = urlsplit(location)
    return (parts.path or "/") + (f"?{parts.query}" if parts.query else "")


class Customers:
    def __init__(self, plan_path, records_path):
        self.plan_path = plan_path
        self.lock = threading.Lock()
        self.stopping = threading.Event()
        self.seen = None
        self.plan = None
        self.pace = None
        self.taken = 0
        self.jars = {}
        self.pages = {}
        self.workers = []
        self.out = open(records_path, "a+", encoding="ascii")
        self.out.seek(0, os.SEEK_END)
        if self.out.tell():
            self.out.seek(self.out.tell() - 1)
            if self.out.read(1) != "\n":
                self.out.write("\n")
        self.out.seek(0, os.SEEK_END)

    def look(self):
        try:
            changed = os.stat(self.plan_path).st_mtime_ns
        except FileNotFoundError:
            self.stopping.set()
            return
        if changed == self.seen:
            return
        try:
            with open(self.plan_path, encoding="utf-8") as given:
                plan = json.load(given)
        except (OSError, ValueError):
            return
        self.seen = changed
        with self.lock:
            self.plan = plan
            if self.pace is None:
                self.pace = Pace(plan["rate"])
            self.pace.rate = plan["rate"]

    def wanted(self):
        return min(WORKERS_MAX, 2 + int(self.plan["rate"] * 2))

    def staff(self):
        self.workers = [worker for worker in self.workers if worker.is_alive()]
        for index in range(len(self.workers), self.wanted()):
            worker = threading.Thread(target=self.work, args=(index,), daemon=True)
            worker.start()
            self.workers.append(worker)

    def run(self):
        while not self.stopping.is_set():
            self.look()
            if self.plan is not None and not self.stopping.is_set():
                self.staff()
            self.stopping.wait(LOOK_EVERY)

    def work(self, index):
        while not self.stopping.is_set() and index < self.wanted():
            with self.lock:
                plan = self.plan
                flow = plan["flows"][self.taken % len(plan["flows"])]
                self.taken += 1
            self.perform(plan, flow)

    def perform(self, plan, flow):
        answer = None
        for step in flow["steps"]:
            form = dict(step["form"]) if "form" in step else None
            if step.get("csrf"):
                found = TOKEN.search(answer.page) if answer else None
                if found is None:
                    return
                form["csrfmiddlewaretoken"] = found.group(1).decode("ascii", "replace")
            answer = self.send(plan, flow, step["step"], step["method"], step["path"], form)
            if step.get("follow") and answer.status in REDIRECTS and answer.location:
                answer = self.send(plan, flow, "redirect", "GET", target_path(answer.location), None)
            if self.stopping.is_set():
                return

    def headers(self, plan, flow, marker, form):
        user = plan["users"][flow["user"]]
        headers = {
            "Host": plan["host"],
            "User-Agent": user["agent"],
            "Accept": ACCEPT,
            "Accept-Language": user["language"],
            "Accept-Encoding": "gzip, deflate",
            "Connection": "close",
            MARKER: marker,
        }
        jar = self.jars.get(flow["user"]) or {}
        if jar:
            headers["Cookie"] = "; ".join(f"{name}={value}" for name, value in jar.items())
        if flow["user"] in self.pages:
            headers["Referer"] = self.pages[flow["user"]]
        if form is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            headers["Origin"] = f"http://{plan['host']}"
        return headers

    def exchange(self, user, method, path, headers, body):
        target = urlsplit(user["target"])
        bind = user.get("bind") or ""
        connection = http.client.HTTPConnection(
            target.hostname, target.port or 80, timeout=TIMEOUT,
            source_address=(bind, 0) if bind else None,
        )
        answer = Answer(source=bind)
        try:
            connection.connect()
            answer.source = connection.sock.getsockname()[0]
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            answer.status = response.status
            answer.location = response.getheader("Location") or ""
            answer.cookies = response.msg.get_all("Set-Cookie") or []
            answer.page = opened(response.read(BODY_KEPT), response.getheader("Content-Encoding") or "")
        except (OSError, http.client.HTTPException):
            pass
        finally:
            connection.close()
        return answer

    def send(self, plan, flow, step, method, path, form):
        self.pace.wait()
        user = plan["users"][flow["user"]]
        marker = str(uuid.uuid4())
        body = urlencode(form).encode() if form is not None else None
        sent_at = datetime.now(timezone.utc).isoformat()
        started = time.monotonic()
        answer = self.exchange(user, method, path, self.headers(plan, flow, marker, form), body)
        jar = self.jars.setdefault(flow["user"], {})
        for cookie in answer.cookies:
            name, _, value = cookie.split(";", 1)[0].partition("=")
            jar[name.strip()] = value.strip()
        if answer.status:
            self.pages[flow["user"]] = f"http://{plan['host']}{path}"
        self.record({
            "marker": marker,
            "action": flow["action"],
            "step": step,
            "user": user["id"],
            "origin": user["origin"],
            "source_ip": answer.source,
            "method": method,
            "path": path,
            "status": answer.status,
            "refused_by": "app" if answer.status == 403 and CSRF_REFUSED in answer.page else "",
            "sent_at": sent_at,
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        })
        return answer

    def record(self, record):
        line = json.dumps(record, ensure_ascii=True, separators=(",", ":")) + "\n"
        with self.lock:
            self.out.write(line)
            self.out.flush()


def main(plan_path, records_path):
    customers = Customers(plan_path, records_path)
    signal.signal(signal.SIGTERM, lambda *_: customers.stopping.set())
    customers.run()
    for worker in customers.workers:
        worker.join(TIMEOUT + 1)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])

from __future__ import annotations

import os
import re
import sys
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar

HOST = "fsl-pfsense"

def mgmt_address(segments, host=HOST):
    for segment in segments:
        if segment.id == "mgmt":
            for node in segment.nodes:
                if node.name == host:
                    return node.address
    return None

def login(address):
    base = f"http://{address}:80"
    user = os.environ.get("PFSENSE_USER", "admin")
    secret = os.environ.get("PFSENSE_PASSWORD", "pfsense")
    jar = CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    opener.addheaders = [("Host", address)]
    try:
        page = opener.open(base + "/", timeout=10).read().decode("utf8", "replace")
        token = re.search(r'sid:[^"]+', page)
        form = urllib.parse.urlencode({
            "__csrf_magic": token.group(0) if token else "",
            "usernamefld": user,
            "passwordfld": secret,
            "login": "Sign In",
        }).encode()
        opener.open(urllib.request.Request(base + "/index.php", data=form), timeout=10).read()
    except Exception:
        return None
    return next((cookie.value for cookie in jar if cookie.name == "PHPSESSID"), None)

def authenticated(address, session):
    request = urllib.request.Request(f"http://{address}:80/index.php")
    request.add_header("Host", address)
    request.add_header("Cookie", f"PHPSESSID={session}")
    try:
        body = urllib.request.urlopen(request, timeout=10).read().decode("utf8", "replace")
    except Exception:
        return False
    return "usernamefld" not in body

def primed_line(address, session):
    return f"http://{address}:80 {address} {session}"

def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "fsl.settings")
    import django

    django.setup()
    from range import substrate

    try:
        segments = substrate().describe().segments
    except Exception:
        return 1
    address = mgmt_address(segments)
    if not address:
        return 1
    if "--check" in sys.argv:
        current = sys.argv[sys.argv.index("--check") + 1 :]
        if current and current[0] and authenticated(address, current[0]):
            return 0
    session = login(address)
    if not session:
        return 2
    print(primed_line(address, session))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

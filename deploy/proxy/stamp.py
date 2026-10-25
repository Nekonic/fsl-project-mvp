from pathlib import Path

MARKER_HEADER = "X-Request-ID"
LABEL_FILE = Path("/var/lib/session/active")

def _read(path):
    try:
        return path.read_text().strip()
    except OSError:
        return ""

def request(flow):
    marker = _read(LABEL_FILE)
    if marker and MARKER_HEADER not in flow.request.headers:
        flow.request.headers[MARKER_HEADER] = marker

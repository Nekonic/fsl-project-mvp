from pathlib import Path

MARKER_HEADER = "X-FSL-Case"
LABEL_FILE = Path("/label/active")
ORIGIN_FILE = Path("/label/origin")

def _read(path):
    try:
        return path.read_text().strip()
    except OSError:
        return ""

def request(flow):
    marker = _read(LABEL_FILE)
    if marker:
        flow.request.headers[MARKER_HEADER] = marker

    origin = _read(ORIGIN_FILE)
    if not origin:
        return

                                                                              
                                                                         
                                         
    asked_for = flow.request.host_header
    flow.request.host = f"waf-{origin}"
    if asked_for:
        flow.request.host_header = asked_for

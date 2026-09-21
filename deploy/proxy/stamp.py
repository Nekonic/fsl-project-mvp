"""Stamp the case marker, and send the request out of the chosen segment.

The platform writes both files: the marker when a labelled window opens, and
the origin when someone picks one in the console. Reading them per request,
rather than holding state, means this proxy needs no API and no restart.

The marker is what lets one piece of free-form traffic be scored by both
strategies - the marker from here, the source IP and time from the window -
so the same case can be correlated either way and the answers compared.

The origin is why nobody has to type an internal name. This proxy sits on
every origin segment, so which of its addresses an alert carries is decided by
which of the target's addresses it connects to. Rewriting the connection host
while leaving the Host header alone means the attacker types the target's real
name and the console decides where the traffic appears to come from.
"""

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

    # Keep what the attacker asked for: the target answers to one name, and an
    # alert that recorded the routing name instead would say the site was
    # attacked under a name nobody typed.
    asked_for = flow.request.host_header
    flow.request.host = f"waf-{origin}"
    if asked_for:
        flow.request.host_header = asked_for

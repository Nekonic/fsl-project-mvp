"""Stamp the active case marker onto everything the attacker sends.

The platform writes the marker file when a labelled window opens and empties it
when the window closes. Reading it per request, rather than holding state,
means this proxy needs no API and no restart.

This is what lets one piece of free-form traffic be scored by both strategies:
the marker comes from here, the source IP and time come from the window, and
the same case can be correlated either way and the answers compared.
"""

from pathlib import Path

MARKER_HEADER = "X-FSL-Case"
LABEL_FILE = Path("/label/active")


def request(flow):
    try:
        marker = LABEL_FILE.read_text().strip()
    except OSError:
        return
    if marker:
        flow.request.headers[MARKER_HEADER] = marker

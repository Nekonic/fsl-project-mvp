"""Console pages. They are handed no data at all.

Every value is filled in by the browser fetching /api/, and the session number
comes out of the URL rather than out of a template variable. Rendering on the
server would create behaviour that exists only in the UI, and then an agent
could not take a human's place later.
"""

from django.shortcuts import render


def main(request):
    return render(request, "console/main.html")


def session(request, session_id):
    return render(request, "console/session.html")


def red(request, session_id):
    return render(request, "console/red.html")


def blue(request, session_id):
    return render(request, "console/blue.html")


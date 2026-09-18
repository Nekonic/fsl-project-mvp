"""Console pages. They are handed no data at all.

Every value is filled in by the browser fetching /api/. Rendering on the server
would create behaviour that exists only in the UI, and then an agent could not
take a human's place later.
"""

from django.shortcuts import render


def score(request):
    return render(request, "blueteam/score.html")


def detections(request):
    return render(request, "blueteam/detections.html")


def rules(request):
    return render(request, "blueteam/rules.html")

from django.shortcuts import render
from django.views.decorators.clickjacking import xframe_options_sameorigin

def main(request):
    return render(request, "console/main.html")

def session(request, session_id):
    return render(request, "console/session.html")

def red(request, session_id):
    return render(request, "console/red.html")

def blue(request, session_id):
    return render(request, "console/blue.html")

@xframe_options_sameorigin
def network_map(request, session_id):
    return render(request, "console/map.html")

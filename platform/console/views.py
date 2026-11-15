from django.shortcuts import render
from django.views.decorators.clickjacking import xframe_options_sameorigin

def login(request):
    return render(request, "console/login.html")

def signup(request):
    return render(request, "console/signup.html")

def users(request):
    return render(request, "console/users.html")

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

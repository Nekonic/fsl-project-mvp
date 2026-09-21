from django.shortcuts import render

def main(request):
    return render(request, "console/main.html")

def session(request, session_id):
    return render(request, "console/session.html")

def red(request, session_id):
    return render(request, "console/red.html")

def blue(request, session_id):
    return render(request, "console/blue.html")

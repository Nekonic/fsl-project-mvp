"""콘솔 화면. 데이터는 하나도 넘기지 않는다.

모든 값은 브라우저가 /api/ 를 fetch 해서 채운다. 서버에서 렌더하면
화면에서만 되는 동작이 생기고, 나중에 사람 자리에 에이전트를 넣을 수 없다.
"""

from django.shortcuts import render


def score(request):
    return render(request, "blueteam/score.html")


def detections(request):
    return render(request, "blueteam/detections.html")


def rules(request):
    return render(request, "blueteam/rules.html")

from django.urls import path
from rest_framework.views import APIView

from cr.urls import urlpatterns as served


class Broken(APIView):
    permission_classes = []

    def get(self, request):
        raise RuntimeError("a bug")


urlpatterns = [*served, path("broken/", Broken.as_view())]

handler404 = "cr.handler.not_found"
handler500 = "cr.handler.server_error"

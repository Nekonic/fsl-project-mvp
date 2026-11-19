from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView

urlpatterns = [
    path("api/", include("accounts.urls")),
    path("api/", include("events.urls")),
    path("api/", include("content.urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
]

handler400 = "cr.handler.bad_request"
handler403 = "cr.handler.denied"
handler404 = "cr.handler.not_found"
handler500 = "cr.handler.server_error"

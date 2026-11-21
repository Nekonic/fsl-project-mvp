from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView

from cr import schema
from training import urls as training


class SideSchema(SpectacularAPIView):
    side = ""

    @property
    def custom_settings(self):
        return schema.side_settings(self.side)


urlpatterns = [
    path("api/", include("users.urls")),
    path("api/", include("telemetry.urls")),
    path("api/", include(training.content_urls)),
    path("api/", include(training.defence_urls)),
    path("api/", include(training.attack_urls)),
    path("api/", include(training.round_urls)),
    path("", include(training.gate)),
    path("", include(training.site)),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/schema/attack/", SideSchema.as_view(side="attack"), name="schema-attack"),
    path("api/schema/defence/", SideSchema.as_view(side="defence"), name="schema-defence"),
]

handler400 = "cr.handler.bad_request"
handler403 = "cr.handler.denied"
handler404 = "cr.handler.not_found"
handler500 = "cr.handler.server_error"

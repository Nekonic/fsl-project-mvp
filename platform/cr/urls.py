from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView

from cr import schema
from defence import urls as defence
from match import urls as match


class SideSchema(SpectacularAPIView):
    side = ""

    @property
    def custom_settings(self):
        return schema.side_settings(self.side)


urlpatterns = [
    path("api/", include("accounts.urls")),
    path("api/", include("events.urls")),
    path("api/", include("content.urls")),
    path("api/", include(defence.urlpatterns)),
    path("api/", include("attack.urls")),
    path("api/", include(match.urlpatterns)),
    path("api/", include("lessons.urls")),
    path("", include(defence.gate)),
    path("", include(match.site)),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/schema/attack/", SideSchema.as_view(side="attack"), name="schema-attack"),
    path("api/schema/defence/", SideSchema.as_view(side="defence"), name="schema-defence"),
]

handler400 = "cr.handler.bad_request"
handler403 = "cr.handler.denied"
handler404 = "cr.handler.not_found"
handler500 = "cr.handler.server_error"

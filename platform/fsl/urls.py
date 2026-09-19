"""Every route in the project.

Two apps' worth of routing is not worth three files and three copies of the
same two imports.
"""

from django.urls import path

from api import views
from blueteam import views as console

urlpatterns = [
    path("api/sessions/", views.create_session),
    path("api/sessions/<int:session_id>/", views.session_detail),
    path("api/sessions/<int:session_id>/close/", views.close_session),
    path("api/sessions/<int:session_id>/cases/", views.session_cases),
    path("api/sessions/<int:session_id>/ingest/", views.ingest_detections),
    path("api/sessions/<int:session_id>/detections/", views.session_detections),
    path("api/sessions/<int:session_id>/score/", views.session_score),
    path("api/rules/", views.current_rules),
    path("api/rules/validate/", views.validate_rules),
    path("api/rules/apply/", views.apply_rules),
    path("", console.score),
    path("detections/", console.detections),
    path("rules/", console.rules),
]

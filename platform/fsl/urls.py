"""Every route in the project.

Two apps' worth of routing is not worth three files and three copies of the
same two imports.
"""

from django.urls import path

from api import views
from console import views as console

urlpatterns = [
    path("api/attacker/", views.attacker_box),
    path("api/attacker/label/", views.attacker_label),
    path("api/wargames/", views.wargame_catalogue),
    path("api/wargames/<str:wargame_id>/cases/", views.wargame_cases),
    path("api/wargames/<str:wargame_id>/objectives/", views.wargame_objectives),
    path("api/sessions/", views.sessions),
    path("api/sessions/<int:session_id>/", views.session_detail),
    path("api/sessions/<int:session_id>/close/", views.close_session),
    path("api/sessions/<int:session_id>/cases/", views.session_cases),
    path("api/sessions/<int:session_id>/attacks/", views.fire_attack),
    path("api/sessions/<int:session_id>/objectives/", views.session_objectives),
    path("api/sessions/<int:session_id>/ingest/", views.ingest_detections),
    path("api/sessions/<int:session_id>/detections/", views.session_detections),
    path("api/sessions/<int:session_id>/score/", views.session_score),
    path("api/detections/<int:detection_id>/", views.detection_detail),
    path("api/rules/", views.current_rules),
    path("api/rules/validate/", views.validate_rules),
    path("api/rules/apply/", views.apply_rules),
    path("", console.main),
    path("session/<int:session_id>/", console.session),
    path("red/<int:session_id>/", console.red),
    path("blue/<int:session_id>/", console.blue),
]

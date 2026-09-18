from django.urls import path

from api import views

urlpatterns = [
    path("sessions/", views.create_session),
    path("sessions/<int:session_id>/", views.session_detail),
    path("sessions/<int:session_id>/close/", views.close_session),
    path("sessions/<int:session_id>/cases/", views.session_cases),
    path("sessions/<int:session_id>/ingest/", views.ingest_detections),
    path("sessions/<int:session_id>/detections/", views.session_detections),
    path("sessions/<int:session_id>/score/", views.session_score),
    path("rules/", views.current_rules),
    path("rules/validate/", views.validate_rules),
    path("rules/apply/", views.apply_rules),
]

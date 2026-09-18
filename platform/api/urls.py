from django.urls import path

from api import views

urlpatterns = [
    path("sessions/", views.create_session),
    path("sessions/<int:session_id>/", views.session_detail),
    path("sessions/<int:session_id>/close/", views.close_session),
    path("sessions/<int:session_id>/cases/", views.session_cases),
]

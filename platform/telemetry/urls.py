from django.urls import path

from telemetry import views

urlpatterns = [
    path("rounds/<int:round_id>/events/", views.RoundEvents.as_view()),
    path("rounds/<int:round_id>/defence/alerts/", views.Alerts.as_view()),
    path("rounds/<int:round_id>/defence/traffic/", views.Traffic.as_view()),
]
